"""
Pytest fixtures for OPC UA testing.

This module provides fixtures to start/stop the OPC UA server for integration tests.
Shared factory functions are in tests/factories.py.
"""
import pytest
import threading
import time
from opcua import Client


@pytest.fixture(scope="module")
def opcua_server():
    """
    Start OPC UA server in background thread for testing.

    The server runs in a daemon thread and stops when tests complete.
    """
    from src.opcua_server import main

    # Start server in background thread (pass empty args to avoid parsing pytest args)
    server_thread = threading.Thread(target=lambda: main([]), daemon=True)
    server_thread.start()

    # Wait for server to initialize
    time.sleep(3)

    yield

    # Server stops automatically when test process ends (daemon thread)


@pytest.fixture
def opcua_client(opcua_server):
    """
    Create and connect an OPC UA client for testing.

    Automatically disconnects after test completes.
    """
    client = Client("opc.tcp://localhost:4840/simantha/")
    client.connect()

    yield client

    client.disconnect()
