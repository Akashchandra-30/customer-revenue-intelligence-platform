using './main.bicep'

param namePrefix = 'revintel'
param environmentName = 'prod'
param pipelineImage = ''          // e.g. 'myregistry.azurecr.io/revintel:2.0.0'
param snowflakeAccount = ''       // e.g. 'xy12345.west-europe.azure'
param snowflakeUser = 'SVC_REVINTEL'
