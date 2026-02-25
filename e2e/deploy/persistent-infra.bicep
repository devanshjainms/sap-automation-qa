// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.
//
// E2E Release Validation — persistent infrastructure.

targetScope = 'resourceGroup'

// ====================================================================
// Parameters
// ====================================================================

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Base name used to derive resource names (lowercase, no hyphens for SA)')
@minLength(3)
@maxLength(16)
param baseName string = 'e2eqa'

@description('Name of the file share that holds WORKSPACES/ directories')
param fileShareName string = 'workspaces'

@description('File share quota in GiB')
@minValue(1)
@maxValue(5120)
param fileShareQuotaGiB int = 100

@description('VNet address prefix')
param vnetAddressPrefix string = '10.101.0.0/16'

@description('Subnet address prefix (must be inside VNet prefix)')
param subnetAddressPrefix string = '10.101.1.0/24'

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

@description('Seed for deterministic password generation (auto-generated)')
@secure()
param passwordSeed string = newGuid()

// ====================================================================
// Variables
// ====================================================================

// Storage account names: 3-24 chars, lowercase letters + digits only.
var storageAccountName = toLower(take('sa${baseName}${uniqueString(resourceGroup().id)}', 24))
var identityName = 'id-${baseName}-e2e'
var vnetName = 'vnet-${baseName}-e2e'
var subnetName = 'snet-${baseName}-deployers'
var privateEndpointName = 'pe-${storageAccountName}-file'
var privateDnsZoneName = 'privatelink.file.core.windows.net'
var keyVaultName = 'kv-${baseName}-${kvSuffix}'
var logAnalyticsWorkspaceName = 'law-${baseName}-e2e'

var kvPrivateEndpointName = 'pe-${keyVaultName}'
var kvPrivateDnsZoneName = 'privatelink.vaultcore.azure.net'

// Self-hosted GitHub Actions runner VM
var runnerVmName = 'vm-${baseName}-runner'
var runnerVmSize = 'Standard_D2s_v5'

// VM credentials — password is generated per-deployment and stored in KV
var vmAdminUsername = 'azureadm'
var vmAdminPassword = '${take(uniqueString(passwordSeed), 12)}Qa1!'

// Tags applied to every resource
var tags = {
  purpose: 'e2e-validation'
  managed_by: 'bicep'
  creationTime: creationTime
}

// Well-known role definition IDs
var storageContributorRoleId = '17d1049b-9a84-46fb-8f53-869881c3d3ab'

// ====================================================================
// User-Assigned Managed Identity
// ====================================================================

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: tags
}

// Federated credential — allows GitHub Actions OIDC login as this MSI
resource federatedCredential 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: managedIdentity
  name: 'github-actions-oidc'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepoSlug}:environment:${githubEnvironment}'
    audiences: [
      'api://AzureADTokenExchange'
    ]
  }
}

// ====================================================================
// Storage Account + File Share
// ====================================================================

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  kind: 'FileStorage'
  sku: {
    name: 'Premium_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: false // NFS requires this to be false
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
    }
  }
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource fileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: fileShareName
  properties: {
    shareQuota: fileShareQuotaGiB
    enabledProtocols: 'NFS'
    rootSquash: 'NoRootSquash'
  }
}

// ====================================================================
// RBAC: MSI → Storage Account Contributor (for CLI access, not mount)
// ====================================================================

resource storageRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, managedIdentity.id, storageContributorRoleId)
  scope: storageAccount
  properties: {
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageContributorRoleId
    )
  }
}

// ====================================================================
// Virtual Network + Subnet
// ====================================================================

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
    subnets: [
      {
        name: subnetName
        properties: {
          addressPrefix: subnetAddressPrefix
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Disabled'
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
            }
          ]
        }
      }
    ]
  }
}

// ====================================================================
// Private Endpoint + Private DNS for Azure Files (NFS)
// ====================================================================

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZoneName
  location: 'global'
  tags: tags
}

resource privateDnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZone
  name: '${vnetName}-link'
  location: 'global'
  tags: tags
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
    registrationEnabled: false
  }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: vnet.properties.subnets[0].id
    }
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: storageAccount.id
          groupIds: [
            'file'
          ]
        }
      }
    ]
  }
}

resource privateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-file'
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
}

// ====================================================================
// Key Vault — central secret store (replaces most GitHub Secrets)
// ====================================================================

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: false
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled' // Kept open during deploy; locked down by deploy script
    accessPolicies: [
      {
        tenantId: subscription().tenantId
        objectId: deployerPrincipalObjectId
        permissions: {
          secrets: ['get', 'set', 'list', 'delete']
        }
      }
      {
        tenantId: subscription().tenantId
        objectId: managedIdentity.properties.principalId
        permissions: {
          secrets: ['get', 'list']
        }
      }
    ]
  }
}

// ====================================================================
// Log Analytics Workspace
// ====================================================================

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// ====================================================================
// Self-Hosted GitHub Actions Runner VM (deallocated by default)
// ====================================================================

resource runnerNic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: '${runnerVmName}-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: {
            id: vnet.properties.subnets[0].id
          }
          privateIPAllocationMethod: 'Dynamic'
        }
      }
    ]
  }
}

resource runnerVm 'Microsoft.Compute/virtualMachines@2024-03-01' = {
  name: runnerVmName
  location: location
  tags: union(tags, {
    role: 'github-runner'
  })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    hardwareProfile: {
      vmSize: runnerVmSize
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: 'Premium_LRS'
        }
        diskSizeGB: 64
      }
    }
    osProfile: {
      computerName: runnerVmName
      adminUsername: vmAdminUsername
      adminPassword: vmAdminPassword
      linuxConfiguration: {
        disablePasswordAuthentication: false
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: runnerNic.id
        }
      ]
    }
  }
}

// Install GitHub Actions runner agent (configure manually with token after deploy)
resource runnerSetup 'Microsoft.Compute/virtualMachines/extensions@2024-03-01' = {
  parent: runnerVm
  name: 'install-runner'
  location: location
  properties: {
    publisher: 'Microsoft.Azure.Extensions'
    type: 'CustomScript'
    typeHandlerVersion: '2.1'
    autoUpgradeMinorVersion: true
    settings: {}
    protectedSettings: {
      commandToExecute: 'set -e; export RUNNER_DIR=/opt/actions-runner; export RUNNER_USER=${vmAdminUsername}; apt-get update -qq && apt-get install -y -qq curl jq git docker.io; usermod -aG docker ${vmAdminUsername}; mkdir -p $RUNNER_DIR && cd $RUNNER_DIR; LATEST=$(curl -sL https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name | sed s/v//); curl -sL https://github.com/actions/runner/releases/download/v$LATEST/actions-runner-linux-x64-$LATEST.tar.gz | tar xz; chown -R ${vmAdminUsername}:${vmAdminUsername} $RUNNER_DIR; echo "Runner v$LATEST installed at $RUNNER_DIR. Register with: ./config.sh --url <repo-url> --token <token> --labels e2e-runner --unattended"'
    }
  }
}

// Auto-shutdown at 00:00 UTC daily (safety net for cost control)
resource autoShutdown 'Microsoft.DevTestLab/schedules@2018-09-15' = {
  name: 'shutdown-computevm-${runnerVmName}'
  location: location
  tags: tags
  properties: {
    status: 'Enabled'
    taskType: 'ComputeVmShutdownTask'
    dailyRecurrence: {
      time: '0000'
    }
    timeZoneId: 'UTC'
    notificationSettings: {
      status: 'Disabled'
    }
    targetResourceId: runnerVm.id
  }
}

// ====================================================================
// Key Vault Secrets — all infrastructure outputs
// ====================================================================

resource secretLocation 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-azure-location'
  properties: { value: location }
}

resource secretSubnetId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-vnet-subnet-id'
  properties: { value: vnet.properties.subnets[0].id }
}

resource secretIdentityId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-user-assigned-identity-id'
  properties: { value: managedIdentity.id }
}

resource secretStorageAccount 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-storage-account-name'
  properties: { value: storageAccount.name }
}

resource secretFileShare 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-file-share-name'
  properties: { value: fileShare.name }
}

resource secretLawsWorkspaceId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-laws-workspace-id'
  properties: { value: logAnalyticsWorkspace.properties.customerId }
}

resource secretLawsResourceGroup 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-laws-resource-group'
  properties: { value: resourceGroup().name }
}

resource secretLawsWorkspaceName 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-laws-workspace-name'
  properties: { value: logAnalyticsWorkspace.name }
}

resource secretTelemetryEnabled 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-telemetry-enabled'
  properties: { value: 'true' }
}

resource secretVmUsername 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-vm-admin-username'
  properties: {
    value: vmAdminUsername
    contentType: 'username'
  }
}

resource secretVmPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-vm-admin-password'
  properties: {
    value: vmAdminPassword
    contentType: 'password'
  }
}

resource secretRunnerVmName 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-runner-vm-name'
  properties: {
    value: runnerVm.name
    contentType: 'vm-name'
  }
}

resource secretRunnerRg 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'e2e-runner-resource-group'
  properties: {
    value: resourceGroup().name
    contentType: 'resource-group'
  }
}

// ====================================================================
// Key Vault Private Endpoint + DNS (created AFTER all secrets)
// ====================================================================

resource kvPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: kvPrivateDnsZoneName
  location: 'global'
  tags: tags
}

resource kvPrivateDnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: kvPrivateDnsZone
  name: '${vnetName}-kv-link'
  location: 'global'
  tags: tags
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
    registrationEnabled: false
  }
}

resource kvPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: kvPrivateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: vnet.properties.subnets[0].id
    }
    privateLinkServiceConnections: [
      {
        name: kvPrivateEndpointName
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

resource kvPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: kvPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-vaultcore'
        properties: {
          privateDnsZoneId: kvPrivateDnsZone.id
        }
      }
    ]
  }
}


// ====================================================================
// Outputs
// ====================================================================
//
// Minimum GitHub Secrets required:
//   AZURE_CLIENT_ID, AZURE_TENANT_ID, E2E_AZURE_SUBSCRIPTION_ID,
//   E2E_KEY_VAULT_NAME  (= keyVaultName output below)
// Everything else is loaded from Key Vault at workflow runtime.

output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri

output userAssignedIdentityId string = managedIdentity.id
output userAssignedIdentityClientId string = managedIdentity.properties.clientId
output userAssignedIdentityPrincipalId string = managedIdentity.properties.principalId

output storageAccountName string = storageAccount.name
output fileShareNameOutput string = fileShare.name

output subnetId string = vnet.properties.subnets[0].id
output vnetNameOutput string = vnet.name
output subnetNameOutput string = vnet.properties.subnets[0].name

output logAnalyticsWorkspaceId string = logAnalyticsWorkspace.properties.customerId
output logAnalyticsWorkspaceNameOutput string = logAnalyticsWorkspace.name

output vmAdminUsername string = vmAdminUsername

output runnerVmName string = runnerVm.name
output runnerPrivateIp string = runnerNic.properties.ipConfigurations[0].properties.privateIPAddress
