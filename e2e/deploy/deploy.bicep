// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.
//
// E2E Release Validation — subscription-level entry point.
// Creates the resource group and deploys all persistent infrastructure.

targetScope = 'subscription'

// ====================================================================
// Parameters
// ====================================================================

@description('Azure region for all resources')
param location string = 'swedencentral'

@description('Name of the resource group to create')
param resourceGroupName string = 'e2e-sap-automation-qa-1'

@description('Base name used to derive resource names')
@minLength(3)
@maxLength(16)
param baseName string = 'e2eqa'

@description('Object ID of the deploying user/principal (for Key Vault access policies)')
param deployerPrincipalObjectId string

@description('Random suffix for Key Vault name (avoids soft-delete collisions)')
@minLength(4)
@maxLength(8)
param kvSuffix string

@description('GitHub repo slug for OIDC federation (e.g. "Azure/sap-automation-qa")')
param githubRepoSlug string = 'Azure/sap-automation-qa'

@description('GitHub environment name for OIDC federation')
param githubEnvironment string = 'e2e'

@description('UTC timestamp for resource tagging (auto-generated)')
param creationTime string = utcNow('yyyy-MM-ddTHH:mm:ssZ')

// ====================================================================
// Resource Group
// ====================================================================

var tags = {
  purpose: 'e2e-validation'
  managed_by: 'bicep'
  creationTime: creationTime
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

// ====================================================================
// Persistent Infrastructure (module deployment into RG)
// ====================================================================

module persistentInfra './persistent-infra.bicep' = {
  name: 'persistent-infra-${uniqueString(rg.id)}'
  scope: rg
  params: {
    location: location
    baseName: baseName
    deployerPrincipalObjectId: deployerPrincipalObjectId
    kvSuffix: kvSuffix
    githubRepoSlug: githubRepoSlug
    githubEnvironment: githubEnvironment
    creationTime: creationTime
  }
}

// ====================================================================
// Outputs (forwarded from module)
// ====================================================================

output resourceGroupName string = rg.name
output keyVaultName string = persistentInfra.outputs.keyVaultName
output keyVaultUri string = persistentInfra.outputs.keyVaultUri
output userAssignedIdentityId string = persistentInfra.outputs.userAssignedIdentityId
output userAssignedIdentityClientId string = persistentInfra.outputs.userAssignedIdentityClientId
output storageAccountName string = persistentInfra.outputs.storageAccountName
output subnetId string = persistentInfra.outputs.subnetId
output vmAdminUsername string = persistentInfra.outputs.vmAdminUsername
