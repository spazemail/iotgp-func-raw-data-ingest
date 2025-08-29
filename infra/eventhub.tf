# Azure Event Hub
# Create Event Hub for driver function telemetry messages
resource "azurerm_eventhub" "eventhub_driver_messages" {
  name                              = "${var.app_acronym}-${var.environment}-eventhub-${var.function_name}-${var.seq_number}-${var.location_acronym}"
  namespace_id                      = data.azurerm_eventhub_namespace.eventhubs_namespace.id
  message_retention                 = 1
  partition_count                   = 2
  status                            = "Active"
}

## Consumer group for the function
resource "azurerm_eventhub_consumer_group" "eventhub_driver_message_consumer_group" {
  name                              = "function-consumer"
  namespace_name                    = data.azurerm_eventhub_namespace.eventhubs_namespace.name
  eventhub_name                     = azurerm_eventhub.eventhub_driver_messages.name
  resource_group_name               = var.resource_group
}