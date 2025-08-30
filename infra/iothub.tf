# Route DeviceMessages ('Raw') to the EXISTING custom EH endpoint
resource "azurerm_iothub_route" "to_builtin_events" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "SqlIngestionToEventHub2"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'Raw'"   # or just "true" to test
  endpoint_names = ["events"]                     # built-in endpoint name is EXACTLY "events"
  enabled        = true
}
