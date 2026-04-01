using '../main.bicep'

param baseName        = 'isis-rec'
param environment     = 'prod'
param appServiceSku   = 'B2'
param mysqlAdminLogin = 'mysqladmin'
param mysqlSku        = 'Standard_B1ms'

// Valores sensibles se inyectan desde GitHub Actions Secrets
// param mysqlAdminPassword = <desde secret>
// param entraClientId      = <desde secret>
// param entraHtenantId     = <desde secret>
// param entraClientSecret  = <desde secret>
