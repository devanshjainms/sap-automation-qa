// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.
//
// E2E Release Validation — main deployment template.


targetScope = 'resourceGroup'

@description('Azure region')
param location string = resourceGroup().location

@description('Admin username for all VMs')
param adminUsername string = 'azureadm'

@description('Admin password for all VMs')
@secure()
param adminPassword string

@description('VM size for deployers')
param vmSize string = 'Standard_D4s_v5'

@description('Resource ID of the existing subnet for deployer VMs')
param subnetId string

@description('Storage account name for Azure Files workspace share (empty = skip mount)')
param storageAccountName string = ''

@description('File share name containing WORKSPACES/')
param fileShareName string = 'workspaces'

@description('Unique suffix for resource names')
param nameSuffix string = utcNow('yyyyMMddHHmm')

@description('Deploy RHEL VM')
param deployRhel bool = true

@description('Deploy SLES VM')
param deploySles bool = true

@description('Deploy Ubuntu VM')
param deployUbuntu bool = true

@description('Tags applied to all resources')
param tags object = {
  purpose: 'e2e-validation'
}

@description('Resource ID of the user-assigned managed identity')
param userAssignedIdentityId string


// ---- VM image references ----
var vmImages = {
  rhel: {
    publisher: 'RedHat'
    offer: 'RHEL'
    sku: '96-gen2'
    version: 'latest'
  }
  sles: {
    publisher: 'SUSE'
    offer: 'sles-15-sp7'
    sku: 'gen2'
    version: 'latest'
  }
  ubuntu: {
    publisher: 'Canonical'
    offer: 'ubuntu-24_04-lts'
    sku: 'server'
    version: 'latest'
  }
}


// ---- Deploy RHEL VM ----
module rhelVm 'deployer-vm.bicep' = if (deployRhel) {
  name: 'deploy-rhel-${nameSuffix}'
  params: {
    vmName: 'vm-e2e-rhel-${nameSuffix}'
    location: location
    adminUsername: adminUsername
    adminPassword: adminPassword
    vmSize: vmSize
    imagePublisher: vmImages.rhel.publisher
    imageOffer: vmImages.rhel.offer
    imageSku: vmImages.rhel.sku
    imageVersion: vmImages.rhel.version
    subnetId: subnetId
    storageAccountName: storageAccountName
    fileShareName: fileShareName
    userAssignedIdentityId: userAssignedIdentityId
    tags: tags
  }
}


// ---- Deploy SLES VM ----
module slesVm 'deployer-vm.bicep' = if (deploySles) {
  name: 'deploy-sles-${nameSuffix}'
  params: {
    vmName: 'vm-e2e-sles-${nameSuffix}'
    location: location
    adminUsername: adminUsername
    adminPassword: adminPassword
    vmSize: vmSize
    imagePublisher: vmImages.sles.publisher
    imageOffer: vmImages.sles.offer
    imageSku: vmImages.sles.sku
    imageVersion: vmImages.sles.version
    subnetId: subnetId
    storageAccountName: storageAccountName
    fileShareName: fileShareName
    userAssignedIdentityId: userAssignedIdentityId
    tags: tags
  }
}


// ---- Deploy Ubuntu VM ----
module ubuntuVm 'deployer-vm.bicep' = if (deployUbuntu) {
  name: 'deploy-ubuntu-${nameSuffix}'
  params: {
    vmName: 'vm-e2e-ubuntu-${nameSuffix}'
    location: location
    adminUsername: adminUsername
    adminPassword: adminPassword
    vmSize: vmSize
    imagePublisher: vmImages.ubuntu.publisher
    imageOffer: vmImages.ubuntu.offer
    imageSku: vmImages.ubuntu.sku
    imageVersion: vmImages.ubuntu.version
    subnetId: subnetId
    storageAccountName: storageAccountName
    fileShareName: fileShareName
    userAssignedIdentityId: userAssignedIdentityId
    tags: tags
  }
}


// ---- Outputs ----
output rhelVmName string = deployRhel ? rhelVm.outputs.vmName : ''
output rhelPrivateIp string = deployRhel ? rhelVm.outputs.privateIpAddress : ''

output slesVmName string = deploySles ? slesVm.outputs.vmName : ''
output slesPrivateIp string = deploySles ? slesVm.outputs.privateIpAddress : ''

output ubuntuVmName string = deployUbuntu ? ubuntuVm.outputs.vmName : ''
output ubuntuPrivateIp string = deployUbuntu ? ubuntuVm.outputs.privateIpAddress : ''
