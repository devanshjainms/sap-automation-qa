// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.
//
// Bicep module: single E2E deployer VM.
//
// Deploys a Linux VM into an existing VNet/subnet with:
// - No public IP (private VNet only)
// - User-assigned managed identity for Azure resource access
// - Azure Files share mounted at /mnt/workspaces
// - Password authentication

@description('VM name')
param vmName string

@description('Azure region')
param location string = resourceGroup().location

@description('Admin username')
param adminUsername string = 'azureadm'

@description('Admin password')
@secure()
param adminPassword string

@description('VM size')
param vmSize string = 'Standard_D4s_v5'

@description('OS image publisher')
param imagePublisher string

@description('OS image offer')
param imageOffer string

@description('OS image SKU')
param imageSku string

@description('OS image version')
param imageVersion string = 'latest'

@description('Resource ID of the existing subnet')
param subnetId string

@description('Storage account name for Azure Files (empty = skip mount)')
param storageAccountName string = ''

@description('File share name containing WORKSPACES/')
param fileShareName string = 'workspaces'

@description('Resource ID of the user-assigned managed identity')
param userAssignedIdentityId string

@description('Tags applied to all resources')
param tags object = {}


// ---- NIC (private IP only) ----
resource nic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: '${vmName}-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: {
            id: subnetId
          }
          privateIPAllocationMethod: 'Dynamic'
        }
      }
    ]
  }
}


// ---- VM ----
resource vm 'Microsoft.Compute/virtualMachines@2024-03-01' = {
  name: vmName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedIdentityId}': {}
    }
  }
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    storageProfile: {
      imageReference: {
        publisher: imagePublisher
        offer: imageOffer
        sku: imageSku
        version: imageVersion
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
      computerName: vmName
      adminUsername: adminUsername
      adminPassword: adminPassword
      linuxConfiguration: {
        disablePasswordAuthentication: false
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nic.id
        }
      ]
    }
  }
}


// ---- Mount Azure Files (custom script extension) ----
// The user-assigned managed identity has the necessary RBAC on the
// storage account. The mount uses the identity-based SMB credential.
resource mountShare 'Microsoft.Compute/virtualMachines/extensions@2024-03-01' = if (!empty(storageAccountName)) {
  parent: vm
  name: 'mount-workspaces'
  location: location
  properties: {
    publisher: 'Microsoft.Azure.Extensions'
    type: 'CustomScript'
    typeHandlerVersion: '2.1'
    autoUpgradeMinorVersion: true
    settings: {}
    protectedSettings: {
      commandToExecute: 'set -e; apt-get update -qq && apt-get install -y -qq nfs-common 2>/dev/null || yum install -y nfs-utils 2>/dev/null || zypper install -y nfs-client 2>/dev/null; mkdir -p /mnt/workspaces; mount -t nfs ${storageAccountName}.file.core.windows.net:/${storageAccountName}/${fileShareName} /mnt/workspaces -o vers=4,minorversion=1,sec=sys,nconnect=4; echo "${storageAccountName}.file.core.windows.net:/${storageAccountName}/${fileShareName} /mnt/workspaces nfs vers=4,minorversion=1,sec=sys,nconnect=4 0 0" >> /etc/fstab'
    }
  }
}


// ---- Outputs ----
output vmName string = vm.name
output privateIpAddress string = nic.properties.ipConfigurations[0].properties.privateIPAddress
