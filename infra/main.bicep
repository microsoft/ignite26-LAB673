@description('Attendee object ID for role assignments')
param principalId string

@description('Foundry and Storage location; Search is always in West Central US')
param location string

@description('Lowercase alphanumeric resource name prefix')
@minLength(3)
@maxLength(8)
param resourcePrefix string = 'lab673'

@description('Optional suffix to avoid recently soft-deleted Foundry account names')
param foundryDeploymentSuffix string = ''

@description('Embedding deployment capacity')
@minValue(1)
@maxValue(200)
param embeddingModelCapacity int = 30

@description('Chat/reasoning model')
param llmModelName string = 'gpt-5.4'

@description('Chat/reasoning model version')
param llmModelVersion string = '2026-03-05'

@description('Chat/reasoning deployment capacity')
@minValue(1)
@maxValue(200)
param llmModelCapacity int = 200

var uniqueSuffix = uniqueString(resourceGroup().id)
var foundrySuffix = empty(foundryDeploymentSuffix) ? uniqueSuffix : '${uniqueSuffix}-${foundryDeploymentSuffix}'
var resourceNames = {
  searchService: '${resourcePrefix}-search-${uniqueSuffix}'
  indexingStorage: '${resourcePrefix}idx${uniqueSuffix}'
  microsoftFoundry: '${resourcePrefix}-foundry-${foundrySuffix}'
  microsoftFoundryProject: '${resourcePrefix}-project-${foundrySuffix}'
}

resource searchService 'Microsoft.Search/searchServices@2026-09-01-preview' = {
  name: resourceNames.searchService
  location: 'westcentralus'
  sku: {
    name: 'serverless'
  }
  properties: {
    publicNetworkAccess: 'enabled'
    networkRuleSet: {
      ipRules: []
    }
    disableLocalAuth: false
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
    semanticSearch: 'standard'
  }
  identity: {
    type: 'SystemAssigned'
  }
}

module indexingStorage 'br/public:avm/res/storage/storage-account:0.33.0' = {
  params: {
    name: resourceNames.indexingStorage
    location: location
    skuName: 'Standard_LRS'
    allowBlobPublicAccess: false
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
    blobServices: {
      containers: [
        {
          name: 'knowledge'
          publicAccess: 'None'
        }
      ]
    }
  }
}

resource indexingStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: resourceNames.indexingStorage
}

resource userStorageContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(indexingStorageAccount.id, principalId, 'Storage Blob Data Contributor')
  scope: indexingStorageAccount
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
  dependsOn: [
    indexingStorage
  ]
}

resource searchStorageReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(indexingStorageAccount.id, searchService.id, 'Storage Blob Data Reader')
  scope: indexingStorageAccount
  properties: {
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
  }
  dependsOn: [
    indexingStorage
  ]
}

var searchUserRoles = [
  '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
]

resource searchUserRoleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in searchUserRoles: {
  name: guid(searchService.id, principalId, roleId)
  scope: searchService
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
  }
}]

resource searchIdentityIndexContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, 'sp-data-reader')
  scope: searchService
  properties: {
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
  }
}

resource microsoftFoundryAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: resourceNames.microsoftFoundry
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: resourceNames.microsoftFoundry
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
    networkAcls: {
      defaultAction: 'Allow'
      virtualNetworkRules: []
      ipRules: []
    }
  }
  identity: {
    type: 'SystemAssigned'
  }
}

resource embeddingModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: microsoftFoundryAccount
  name: 'text-embedding-3-large'
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-large'
      version: '1'
    }
  }
  sku: {
    name: 'GlobalStandard'
    capacity: embeddingModelCapacity
  }
}

resource llmModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: microsoftFoundryAccount
  name: llmModelName
  properties: {
    model: {
      format: 'OpenAI'
      name: llmModelName
      version: llmModelVersion
    }
  }
  sku: {
    name: 'GlobalStandard'
    capacity: llmModelCapacity
  }
  dependsOn: [
    embeddingModelDeployment
  ]
}

resource microsoftFoundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: microsoftFoundryAccount
  name: resourceNames.microsoftFoundryProject
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
  dependsOn: [
    llmModelDeployment
  ]
}

resource projectSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, microsoftFoundryProject.id, '1407120a-92aa-4202-b7e9-c0e197c71c8f')
  scope: searchService
  properties: {
    principalId: microsoftFoundryProject.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f')
  }
}

var searchFoundryRoles = [
  '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  'a97b65f3-24c7-4388-baec-2e87135dc908'
]

resource searchFoundryRoleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in searchFoundryRoles: {
  name: guid(microsoftFoundryAccount.id, searchService.id, roleId)
  scope: microsoftFoundryAccount
  properties: {
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
  }
}]

var foundryUserRoles = [
  '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  'eadc314b-1a2d-4efa-be10-5d325db5065e'
]

resource accountUserRoleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in foundryUserRoles: {
  name: guid(microsoftFoundryAccount.id, principalId, roleId)
  scope: microsoftFoundryAccount
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
  }
}]

resource projectUserRoleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in foundryUserRoles: {
  name: guid(microsoftFoundryProject.id, principalId, roleId)
  scope: microsoftFoundryProject
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
  }
}]

output MICROSOFT_FOUNDRY_PROJECT_ENDPOINT string = 'https://${microsoftFoundryAccount.name}.services.ai.azure.com/api/projects/${microsoftFoundryProject.name}'
output MICROSOFT_FOUNDRY_PROJECT_ID string = microsoftFoundryProject.id
output AZURE_SEARCH_SERVICE_ENDPOINT string = 'https://${searchService.name}.search.windows.net'
output AZURE_SEARCH_SERVICE_NAME string = searchService.name
output INDEXING_STORAGE_ACCOUNT_ID string = indexingStorage.outputs.resourceId
output INDEXING_STORAGE_ACCOUNT_NAME string = indexingStorage.outputs.name
output AZURE_OPENAI_ENDPOINT string = microsoftFoundryAccount.properties.endpoint
output AZURE_OPENAI_SERVICE_NAME string = microsoftFoundryAccount.name
output AZURE_OPENAI_EMBEDDING_DEPLOYMENT string = embeddingModelDeployment.name
output AZURE_OPENAI_CHATGPT_DEPLOYMENT string = llmModelDeployment.name
output AZURE_OPENAI_CHATGPT_MODEL_NAME string = llmModelName
output CONTENTUNDERSTANDING_ENDPOINT string = 'https://${microsoftFoundryAccount.name}.services.ai.azure.com'
output AZURE_TENANT_ID string = tenant().tenantId
