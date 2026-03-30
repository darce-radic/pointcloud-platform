import { test, expect } from '@playwright/test';

test.describe('Viewer Wiring Fixes E2E', () => {
  // We mock the API responses to test the frontend wiring without needing a full backend/DB setup
  
  test.beforeEach(async ({ page }) => {
    // Mock the session/auth
    await page.route('**/api/auth/session', async (route) => {
      await route.fulfill({
        status: 200,
        json: { user: { id: 'test-user', email: 'test@example.com' } }
      });
    });

    // Mock the dataset fetch
    await page.route('**/api/v1/datasets/*', async (route) => {
      await route.fulfill({
        status: 200,
        json: {
          id: 'test-dataset-id',
          name: 'Test Dataset',
          status: 'ready',
          copc_url: 'http://example.com/test.copc.laz'
        }
      });
    });

    // Mock the workflow tools fetch
    await page.route('**/api/v1/workflow-tools', async (route) => {
      await route.fulfill({
        status: 200,
        json: {
          tools: [
            {
              id: 'tool-1',
              name: 'Extract Road Assets',
              description: 'Detect road markings',
              icon: 'road',
              category: 'extraction'
            }
          ]
        }
      });
    });
  });

  test('AI Chat Stream Flow', async ({ page }) => {
    // Navigate to the viewer
    await page.goto('/viewer?id=test-dataset-id');
    
    // Wait for viewer to load
    await expect(page.locator('.cesium-viewer')).toBeVisible({ timeout: 10000 });
    
    // Open the AI Chat panel (assuming there's a button to open it)
    const chatButton = page.getByRole('button', { name: /ai chat/i });
    if (await chatButton.isVisible()) {
      await chatButton.click();
    }
    
    // Mock the SSE stream response
    await page.route('**/api/v1/conversations/stream', async (route) => {
      const streamContent = `data: {"type": "conversation_id", "conversation_id": "new-conv-123"}\n\n` +
                            `data: {"type": "token", "content": "Hello"}\n\n` +
                            `data: {"type": "token", "content": " World"}\n\n` +
                            `data: {"type": "done"}\n\n`;
      
      await route.fulfill({
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive'
        },
        body: streamContent
      });
    });

    // Type a message and send
    const input = page.getByPlaceholder('Ask AI about this dataset...');
    await input.fill('Detect road markings');
    await input.press('Enter');
    
    // Verify the message appears in the chat
    await expect(page.getByText('Hello World')).toBeVisible();
  });

  test('Workflow Tool Execution Flow', async ({ page }) => {
    // Navigate to the viewer
    await page.goto('/viewer?id=test-dataset-id');
    
    // Mock the tool run endpoint
    await page.route('**/api/v1/workflow-tools/tool-1/run', async (route) => {
      await route.fulfill({
        status: 200,
        json: {
          job_id: 'job-123',
          status: 'queued'
        }
      });
    });
    
    // Find the tool button in the toolbar and click it
    const toolButton = page.getByRole('button', { name: /Extract Road Assets/i });
    await expect(toolButton).toBeVisible();
    await toolButton.click();
    
    // Verify that a toast or notification appears indicating the job started
    // This depends on the specific UI implementation, e.g., sonner toast
    await expect(page.getByText(/started/i, { exact: false })).toBeVisible();
  });
});
