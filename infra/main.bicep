// =============================================================
// RECLUTAMIENTO ISIS - Infraestructura Azure (Bicep)
// Despliega: App Service, MySQL Flexible Server, Key Vault
// Parámetros sensibles se reciben desde GitHub Actions / pipeline
// =============================================================

targetScope = 'resourceGroup'

@description('Nombre base del entorno (ej. isis-rec-prod)')
param baseName string = 'isis-rec'

@description('Entorno: dev | staging | prod')
@allowed(['dev', 'staging', 'prod'])
param environment string = 'prod'

@description('Región Azure')
param location string = resourceGroup().location

@description('SKU del App Service Plan')
param appServiceSku string = 'B2'

@description('Versión de Python en App Service')
param pythonVersion string = '3.11'

// MySQL
@description('Login administrador MySQL')
param mysqlAdminLogin string = 'mysqladmin'

@secure()
@description('Password administrador MySQL (mín 8 chars, letras, números, símbolo)')
param mysqlAdminPassword string

@description('SKU del MySQL Flexible Server')
param mysqlSku string = 'Standard_B1ms'

// Entra ID
param entraClientId string
param entraHtenantId string

@secure()
param entraClientSecret string

// Tags comunes
var tags = {
  proyecto: 'reclutamiento-isis'
  entorno: environment
  equipoOwner: 'RRHH'
}

var suffix = '${baseName}-${environment}'

// =============================================================
// App Service Plan
// =============================================================
resource asp 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: 'asp-${suffix}'
  location: location
  tags: tags
  sku: {
    name: appServiceSku
  }
  kind: 'linux'
  properties: {
    reserved: true   // Linux
  }
}

// =============================================================
// App Service (Web App)
// =============================================================
resource webApp 'Microsoft.Web/sites@2023-01-01' = {
  name: 'app-${suffix}'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'   // Managed Identity para Key Vault
  }
  properties: {
    serverFarmId: asp.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|${pythonVersion}'
      appCommandLine: 'bash startup.sh'
      alwaysOn: true
      minTlsVersion: '1.2'
      http20Enabled: true
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'APP_ENV',              value: environment }
        { name: 'MYSQL_HOST',           value: mysqlServer.properties.fullyQualifiedDomainName }
        { name: 'MYSQL_PORT',           value: '3306' }
        { name: 'MYSQL_USER',           value: mysqlAdminLogin }
        { name: 'MYSQL_DATABASE',       value: 'reclutamiento_isis' }
        { name: 'MYSQL_SSL',            value: 'true' }
        { name: 'ENTRA_TENANT_ID',      value: entraHtenantId }
        { name: 'ENTRA_CLIENT_ID',      value: entraClientId }
        { name: 'KEY_VAULT_URI',        value: keyVault.properties.vaultUri }
        // Secretos vía referencia a Key Vault (no se almacenan en texto plano)
        { name: 'MYSQL_PASSWORD',       value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/mysql-password/)' }
        { name: 'ENTRA_CLIENT_SECRET',  value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/entra-client-secret/)' }
        { name: 'SECRET_KEY',           value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/app-secret-key/)' }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'WEBSITE_RUN_FROM_PACKAGE', value: '0' }
      ]
    }
  }
}

// =============================================================
// MySQL Flexible Server
// =============================================================
resource mysqlServer 'Microsoft.DBforMySQL/flexibleServers@2023-10-01-preview' = {
  name: 'mysql-${suffix}'
  location: location
  tags: tags
  sku: {
    name: mysqlSku
    tier: 'Burstable'
  }
  properties: {
    administratorLogin: mysqlAdminLogin
    administratorLoginPassword: mysqlAdminPassword
    version: '8.0.21'
    storage: {
      storageSizeGB: 20
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      // VNet opcional; sin VNet usar firewall con IPs de App Service
    }
  }
}

// Base de datos
resource mysqlDb 'Microsoft.DBforMySQL/flexibleServers/databases@2023-10-01-preview' = {
  parent: mysqlServer
  name: 'reclutamiento_isis'
  properties: {
    charset: 'utf8mb4'
    collation: 'utf8mb4_unicode_ci'
  }
}

// Regla firewall: permitir servicios Azure
resource mysqlFirewallAzure 'Microsoft.DBforMySQL/flexibleServers/firewallRules@2023-10-01-preview' = {
  parent: mysqlServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// =============================================================
// Key Vault
// =============================================================
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${uniqueString(resourceGroup().id)}'
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true        // RBAC en lugar de Access Policies
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enabledForTemplateDeployment: true
  }
}

// Acceso del App Service al Key Vault (Managed Identity)
resource kvRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, webApp.id, 'KeyVaultSecretsUser')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'   // Key Vault Secrets User
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Secretos en Key Vault
resource secretMysqlPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'mysql-password'
  properties: { value: mysqlAdminPassword }
}

resource secretEntraClient 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'entra-client-secret'
  properties: { value: entraClientSecret }
}

resource secretAppKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'app-secret-key'
  properties: { value: uniqueString(resourceGroup().id, baseName) }
}

// =============================================================
// OUTPUTS
// =============================================================
output webAppName string = webApp.name
output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
output mysqlHost string = mysqlServer.properties.fullyQualifiedDomainName
output keyVaultUri string = keyVault.properties.vaultUri
