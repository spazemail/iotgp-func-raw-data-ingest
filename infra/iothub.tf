# Route DeviceMessages (Raw) to the built-in EH-compatible endpoint
resource "azurerm_iothub_route" "to_builtin_events" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "SqlIngestionToBuiltInEvents"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'Raw'"
  endpoint_names = ["events"]   # built-in Event Hubs–compatible endpoint
  enabled        = true
}
