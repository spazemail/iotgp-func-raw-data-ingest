
# Create container to store Function App ZIP
resource "azurerm_storage_container" "function_releases_container" {
  name                  = "function-releases"
  storage_account_id    = data.azurerm_storage_account.function_storage.id
  container_access_type = "private"
}
