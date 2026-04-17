// =============================================================================
// AppScan Custom Dashboard — Azure Bicep Template
// Deploys: App Service (Linux/Docker) + PostgreSQL Flexible Server
//          + Key Vault + Application Insights
// =============================================================================

@description('Base name for all resources (lowercase, no spaces)')
param baseName string = 'appscan-dashboard'

@description('Azure region for deployment')
param location string = resourceGroup().location

@description('PostgreSQL administrator login')
param dbAdminLogin string = 'pgadmin'

@description('PostgreSQL administrator password')
@secure()
param dbAdminPassword string

@description('JWT secret for dashboard authentication')
@secure()
param jwtSecret string

@description('Docker image tag to deploy')
param imageTag string = 'latest'

@description('App Service Plan SKU')
@allowed(['B1', 'B2', 'S1', 'S2', 'P1v3', 'P2v3'])
param appServiceSku string = 'B1'

// ---------------------------------------------------------------------------
// Variables
// ---------------------------------------------------------------------------
var uniqueSuffix = uniqueString(resourceGroup().id, baseName)
var appName = '${baseName}-${uniqueSuffix}'
var dbServerName = '${baseName}-pg-${uniqueSuffix}'
var dbName = 'aspm'
var kvName = '${baseName}-kv-${uniqueSuffix}'
var appInsightsName = '${baseName}-insights-${uniqueSuffix}'
var planName = '${baseName}-plan-${uniqueSuffix}'

// ---------------------------------------------------------------------------
// Application Insights
// ---------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${baseName}-logs-${uniqueSuffix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ---------------------------------------------------------------------------
// Key Vault
// ---------------------------------------------------------------------------
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource secretJwt 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'jwt-secret'
  properties: { value: jwtSecret }
}

resource secretDbPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'db-password'
  properties: { value: dbAdminPassword }
}

// ---------------------------------------------------------------------------
// PostgreSQL Flexible Server
// ---------------------------------------------------------------------------
resource pgServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-12-01-preview' = {
  name: dbServerName
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: dbAdminLogin
    administratorLoginPassword: dbAdminPassword
    storage: { storageSizeGB: 32 }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
  }
}

resource pgDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-12-01-preview' = {
  parent: pgServer
  name: dbName
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

// Allow Azure services to connect (App Service → PostgreSQL)
resource pgFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-12-01-preview' = {
  parent: pgServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ---------------------------------------------------------------------------
// App Service Plan + Web App
// ---------------------------------------------------------------------------
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  kind: 'linux'
  sku: { name: appServiceSku }
  properties: { reserved: true }
}

resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'DOCKER|${appName}.azurecr.io/appscan-dashboard:${imageTag}'
      alwaysOn: appServiceSku != 'B1'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'DATABASE_URL', value: 'postgresql+psycopg://${dbAdminLogin}:${dbAdminPassword}@${pgServer.properties.fullyQualifiedDomainName}:5432/${dbName}?sslmode=require' }
        { name: 'JWT_SECRET', value: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=jwt-secret)' }
        { name: 'FRONTEND_ORIGIN', value: 'https://${appName}.azurewebsites.net' }
        { name: 'WEBSITES_PORT', value: '8000' }
        { name: 'APPINSIGHTS_INSTRUMENTATIONKEY', value: appInsights.properties.InstrumentationKey }
      ]
    }
  }
}

// Grant the Web App's managed identity access to Key Vault secrets
resource kvRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, webApp.id, 'Key Vault Secrets User')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6') // Key Vault Secrets User
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
output webAppName string = webApp.name
output pgServerFqdn string = pgServer.properties.fullyQualifiedDomainName
output keyVaultName string = keyVault.name
output appInsightsName string = appInsights.name
