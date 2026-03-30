import pytest
from unittest.mock import patch, MagicMock
import os
import sys

# Set env vars before importing to prevent sys.exit(1)
os.environ["SUPABASE_URL"] = "http://test"
os.environ["SUPABASE_SERVICE_KEY"] = "test-key"
os.environ["OPENAI_API_KEY"] = "test-key"

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from seed_node_library import make_embedding_text, get_embeddings

def test_make_embedding_text():
    node = {
        "display_name": "Test Node",
        "description": "This is a test node.",
        "tags": ["test", "mock", "node"]
    }
    result = make_embedding_text(node)
    assert "Test Node" in result
    assert "This is a test node." in result
    assert "test, mock, node" in result

@patch("seed_node_library.OpenAI")
def test_get_embeddings_batching(mock_openai_class):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2]) for _ in range(20)]
    mock_client.embeddings.create.return_value = mock_response
    
    texts = ["text" + str(i) for i in range(25)]
    embeddings = get_embeddings(texts, mock_client)
    
    assert mock_client.embeddings.create.call_count == 2
    assert len(embeddings) == 40
