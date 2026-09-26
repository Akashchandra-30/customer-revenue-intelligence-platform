// Azure resources for the Customer & Revenue Intelligence Platform:
//  - ADLS Gen2 storage account + container for the clean / archive / rejects layers
//  - Lifecycle policy moving archived snapshots to cool storage
//  - Container Apps job that runs the Python pipeline daily
//
// Deploy:
//   az group create -n rg-revintel -l westeurope
//   az deployment group create -g rg-revintel -f infra/azure/main.bicep \
//       -p namePrefix=revintel pipelineImage=<registry>/revintel:latest

@description('Short prefix for resource names (3-11 lowercase letters/numbers).')
@minLength(3)
@maxLength(11)
param namePrefix string = 'revintel'

param location string = resourceGroup().location

@description('Container image with this repository (see Dockerfile).')
param pipelineImage string = ''

@description('Cron for the daily pipeline run (UTC).')
param schedule string = '0 5 * * *'

@secure()
@description('Snowflake password for the REVINTEL_LOADER user; stored as a Container Apps secret.')
param snowflakePassword string = ''

param snowflakeAccount string = ''
param snowflakeUser string = 'REVINTEL_LOADER'

var storageName = toLower('${namePrefix}${uniqueString(resourceGroup().id)}')

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take(storageName, 24)
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true // ADLS Gen2
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
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
          name: 'archive-to-cool'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: { blobTypes: [ 'blockBlob' ], prefixMatch: [ 'revintel/archive/', 'revintel/rejects/' ] }
            actions: { baseBlob: { tierToCool: { daysAfterModificationGreaterThan: 30 }, delete: { daysAfterModificationGreaterThan: 730 } } }
          }
        }
      ]
    }
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (!empty(pipelineImage)) {
  name: '${namePrefix}-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = if (!empty(pipelineImage)) {
  name: '${namePrefix}-env'
  location: location
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

resource job 'Microsoft.App/jobs@2024-03-01' = if (!empty(pipelineImage)) {
  name: '${namePrefix}-daily'
  location: location
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 3600
      replicaRetryLimit: 1
      scheduleTriggerConfig: { cronExpression: schedule, parallelism: 1, replicaCompletionCount: 1 }
      secrets: [
        { name: 'storage-conn', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'snowflake-password', value: snowflakePassword }
      ]
    }
    template: {
      containers: [
        {
          name: 'pipeline'
          image: pipelineImage
          args: [ '--target', 'snowflake', '--upload-azure', '--via-azure-stage' ]
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-conn' }
            { name: 'AZURE_STORAGE_CONTAINER', value: 'revintel' }
            { name: 'SNOWFLAKE_ACCOUNT', value: snowflakeAccount }
            { name: 'SNOWFLAKE_USER', value: snowflakeUser }
            { name: 'SNOWFLAKE_PASSWORD', secretRef: 'snowflake-password' }
          ]
        }
      ]
    }
  }
}

output storageAccountName string = storage.name
output snowflakeStageUrl string = 'azure://${storage.name}.blob.${environment().suffixes.storage}/revintel/clean/'
