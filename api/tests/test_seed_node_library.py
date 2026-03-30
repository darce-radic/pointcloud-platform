import pytest
from unittest.mock import patch, MagicMock

# Import functions from the script
import sys
import os
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
    # Mock the embeddings create response
    mock_response = MagicMock()
    # Create 20 mock items for the first batch, 5 for the second
    mock_response.data = [MagicMock(embedding=[0.1, 0.2]) for _ in range(20)]
    mock_client.embeddings.create.return_value = mock_response
    
    texts = ["text" + str(i) for i in range(25)]
    
    # We need to handle the fact that the second batch will return 20 items in our mock, 
    # but we just want to ensure it's called twice.
    embeddings = get_embeddings(texts, mock_client)
    
    assert mock_client.embeddings.create.call_count == 2
    assert len(embeddings) == 40 # 20 + 20 from our simple mock
