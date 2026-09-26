// Azure infrastructure for the Customer & Revenue Intelligence Platform
//
//  - ADLS Gen2 storage (clean / rejects / dq zones) with lifecycle tiering
//  - User-assigned managed identity: blob access without keys, Key Vault secret reads
//  - Key Vault for Snowflake key-pair, Power BI service principal and alert webhook
//  - Log Analytics + Container Apps scheduled job running `revintel run`
//
// Deploy:
//   az group create -n rg-revintel-prod -l westeurope
//   az deployment group create -g rg-revintel-prod -f infra/azure/main.bicep -p infra/azure/main.bicepparam
// Then set secrets:
//   az keyvault secret set --vault-name <kv> -n snowflake-private-key -f rsa_key.p8

@description('Short prefix for resource names (3-11 lowercase letters/numbers).')
@minLength(3)
@maxLength(11)
param namePrefix string = 'revintel'

@allowed(['dev', 'prod'])
param environmentName string = 'prod'

param location string = resourceGroup().location

@description('Pipeline container image, e.g. myregistry.azurecr.io/revintel:1.0.0. Leave empty to deploy storage only.')
param pipelineImage string = ''

@description('Cron for the scheduled run (UTC). Used when not orchestrated by Airflow.')
param schedule string = '0 5 * * *'

param snowflakeAccount string = ''
param snowflakeUser string = 'SVC_REVINTEL'

var suffix = uniqueString(resourceGroup().id)
var tags = { project: 'revintel', environment: environmentName }

// ---------- Identity --------------------------------------------------------------
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-${environmentName}-id'
  location: location
  tags: tags
}

// ---------- Data lake -------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take(toLower('${namePrefix}${environmentName}${suffix}'), 24)
  location: location
  tags: tags
  sku: { name: environmentName == 'prod' ? 'Standard_ZRS' : 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false // identity-based access only
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 14 }
    containerDeleteRetentionPolicy: { enabled: true, days: 14 }
  }
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'revintel'
  properties: { publicAccess: 'None' }
}

resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'tier-old-batches'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: { blobTypes: ['blockBlob'], prefixMatch: ['revintel/clean/', 'revintel/rejects/', 'revintel/dq/'] }
            actions: {
              baseBlob: {
                tierToCool: { daysAfterModificationGreaterThan: 30 }
                tierToArchive: { daysAfterModificationGreaterThan: 180 }
                delete: { daysAfterModificationGreaterThan: 2555 } // 7-year financial retention
              }
            }
          }
        }
      ]
    }
  }
}

// Storage Blob Data Contributor for the pipeline identity
resource blobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, 'blob-contributor')
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------- Secrets -------------------------------------------------------------------
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('${namePrefix}-${environmentName}-${suffix}', 24)
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
    enablePurgeProtection: true
  }
}

// Key Vault Secrets User for the pipeline identity
resource secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, 'secrets-user')
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------- Scheduled pipeline job ------------------------------------------------------
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (!empty(pipelineImage)) {
  name: '${namePrefix}-${environmentName}-logs'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = if (!empty(pipelineImage)) {
  name: '${namePrefix}-${environmentName}-env'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var secretNames = ['snowflake-private-key', 'powerbi-client-secret', 'alert-webhook-url']

resource job 'Microsoft.App/jobs@2024-03-01' = if (!empty(pipelineImage)) {
  name: '${namePrefix}-${environmentName}-daily'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 3600
      replicaRetryLimit: 1
      scheduleTriggerConfig: { cronExpression: schedule, parallelism: 1, replicaCompletionCount: 1 }
      // Secrets are references into Key Vault, resolved with the managed identity
      secrets: [for name in secretNames: {
        name: name
        keyVaultUrl: '${vault.properties.vaultUri}secrets/${name}'
        identity: identity.id
      }]
    }
    template: {
      containers: [
        {
          name: 'pipeline'
          image: pipelineImage
          args: ['run', '--target', environmentName, '--upload-azure', '--load-mode', 'stage']
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'LOG_FORMAT', value: 'json' }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'AZURE_STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
            { name: 'AZURE_STORAGE_CONTAINER', value: 'revintel' }
            { name: 'SNOWFLAKE_ACCOUNT', value: snowflakeAccount }
            { name: 'SNOWFLAKE_USER', value: snowflakeUser }
            { name: 'SNOWFLAKE_PRIVATE_KEY', secretRef: 'snowflake-private-key' }
            { name: 'POWERBI_CLIENT_SECRET', secretRef: 'powerbi-client-secret' }
            { name: 'ALERT_WEBHOOK_URL', secretRef: 'alert-webhook-url' }
          ]
        }
      ]
    }
  }
  dependsOn: [secretsUser, blobContributor]
}

output storageAccountName string = storage.name
output keyVaultName string = vault.name
output managedIdentityClientId string = identity.properties.clientId
output snowflakeStageUrl string = 'azure://${storage.name}.blob.${environment().suffixes.storage}/revintel/clean/'
