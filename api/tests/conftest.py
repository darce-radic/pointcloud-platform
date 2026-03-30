import os
import pytest

# Set environment variables before any application code is imported
os.environ["SUPABASE_URL"] = "http://test-supabase-url"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-service-key"
os.environ["SUPABASE_ANON_KEY"] = "test-anon-key"
os.environ["OPENAI_API_KEY"] = "test-openai-key"
os.environ["STRIPE_SECRET_KEY"] = "test-stripe-key"
os.environ["STRIPE_WEBHOOK_SECRET"] = "test-stripe-webhook"
os.environ["N8N_PAYMENT_FAILED_WEBHOOK"] = "http://test-webhook"
os.environ["N8N_NEW_USER_WEBHOOK"] = "http://test-webhook"
