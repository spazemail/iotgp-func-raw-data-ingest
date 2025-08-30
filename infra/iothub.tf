# Role: Azure Event Hubs Data Sender
resource "azurerm_role_assignment" "iothub_eh_sender" {
  scope                = data.azurerm_eventhub.driver_messages.id   # or the namespace id
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = azurerm_iothub.iothub.identity[0].principal_id
}

# 3) Identity-based endpoint (NO connection_string)
resource "azurerm_iothub_endpoint_eventhub" "iothub_endpoint_eventhub_messages" {
  resource_group_name = var.resource_group
  iothub_id           = azurerm_iothub.iothub.id
  name                = "EventHubMessages2"

  endpoint_uri        = "sb://${data.azurerm_eventhub_namespace.ehns.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_driver_messages.name

  authentication_type = "identityBased"
}

# 4) Route to that endpoint
resource "azurerm_iothub_route" "telemetry_to_custom_eventhub" {
  resource_group_name = var.resource_group
  iothub_name         = azurerm_iothub.iothub.name
  name                = "SqlIngestionToBuiltInEvents"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'Raw'"
  endpoint_names = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.name]
  enabled        = true

  lifecycle {
    replace_triggered_by = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.id]
  }
}
