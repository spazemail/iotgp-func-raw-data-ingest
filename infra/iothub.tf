# Create a Send-only SAS policy on the Event Hub *namespace*
resource "azurerm_eventhub_namespace_authorization_rule" "ehns_send" {
  name                = "iothub-send"
  namespace_name      = data.azurerm_eventhub_namespace.eventhubs_namespace.name
  resource_group_name = var.resource_group
  listen              = false
  send                = true
  manage              = false
}

# IoT Hub → Event Hub endpoint using keyBased auth
resource "azurerm_iothub_endpoint_eventhub" "iothub_endpoint_eventhub_messages" {
  resource_group_name = var.resource_group
  iothub_id           = data.azurerm_iothub.iothub.id
  name                = "EventHubMessages"

  endpoint_uri        = "sb://${data.azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_driver_messages.name

  authentication_type = "keyBased"
  # Use the Send-only connection string
  connection_string   = azurerm_eventhub_namespace_authorization_rule.ehns_send.primary_connection_string
}

# Route Raw messages to the custom EH endpoint (unchanged)
resource "azurerm_iothub_route" "iothub_route_eventhub_messages_endpoint" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "SqlIngestionToEventHub2"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'Raw'"
  endpoint_names = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.name]
  enabled        = true
}
