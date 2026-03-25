# PRD-07: Multi-Tenancy, Billing & Organisations

**Module:** Platform Administration
**Status:** Draft
**Target Audience:** Claude Code

## 1. Overview
The platform is designed as a B2B SaaS application. It must support multi-tenancy (Organizations), role-based access control (RBAC), and subscription billing via Stripe. The current codebase has scaffolded routers for billing and organizations, but they contain hardcoded values and missing database tables.

## 2. User Stories
- As a user, I want to create an organization and invite my team members so we can collaborate on the same point cloud datasets.
- As a team member, I only want to see projects and datasets that belong to my organization.
- As an organization owner, I want to upgrade my subscription plan via Stripe to increase my storage limit.
- As the platform administrator, I do not want users to have access to a "free tier" (per philosophical preference); users must be on a paid plan or an explicitly granted trial.

## 3. Architecture & Components
- **Identity & Auth:** Supabase Auth (PostgreSQL Row Level Security).
- **Billing:** Stripe Checkout & Webhooks.
- **Data Isolation:** All core tables (`projects`, `datasets`, `jobs`) have an `organization_id` foreign key.

## 4. Technical Specifications

### 4.1. Database Schema Additions
The `billing.py` router and several RLS policies reference a `profiles` table that does not exist in the migrations.

**Action:** Create a migration to add the `profiles` table:
```sql
CREATE TABLE IF NOT EXISTS public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  organization_id UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
  stripe_customer_id TEXT,
  subscription_plan TEXT NOT NULL DEFAULT 'trial' CHECK (subscription_plan IN ('trial','professional','business','enterprise')),
  subscription_status TEXT NOT NULL DEFAULT 'active',
  storage_limit_bytes BIGINT NOT NULL DEFAULT 10737418240, -- 10GB default trial
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```
*Note: The default plan is 'trial', explicitly avoiding a 'free' tier.*

### 4.2. Fix Hardcoded Webhooks (`api/routers/billing.py`)
The billing router currently hardcodes n8n webhook URLs for failed payments.

**Action:** Move these to environment variables.
1. Add to `api/config.py`:
   ```python
   N8N_PAYMENT_FAILED_WEBHOOK: str = Field(default="")
   N8N_NEW_USER_WEBHOOK: str = Field(default="")
   ```
2. Update `billing.py` (lines 21-22):
   ```python
   webhook_url = settings.N8N_PAYMENT_FAILED_WEBHOOK
   ```

### 4.3. Stripe Integration
The `POST /billing/create-checkout-session` endpoint currently uses hardcoded `price_id` values based on a `plan_key`.

**Action:** Ensure these `price_id` values are either read from the database or mapped from environment variables (`STRIPE_PRICE_PRO`, `STRIPE_PRICE_BUSINESS`).

### 4.4. Row Level Security (RLS)
Ensure all tables (`datasets`, `projects`, `jobs`, `features`) have RLS policies enabled that restrict `SELECT`, `INSERT`, `UPDATE`, and `DELETE` operations to users who are members of the corresponding `organization_id`.

Example for `datasets`:
```sql
ALTER TABLE public.datasets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view datasets in their organization"
ON public.datasets FOR SELECT
USING (
  organization_id IN (
    SELECT organization_id FROM public.organization_members WHERE user_id = auth.uid()
  )
);
```

## 5. Acceptance Criteria
- [ ] A new user can register, create an organization, and automatically have a `profiles` record created via a Supabase database trigger.
- [ ] The user can generate a Stripe Checkout session URL for the 'professional' plan.
- [ ] The `billing.py` router reads all webhook URLs from environment variables, not hardcoded strings.
- [ ] A user in Organization A cannot query or access a dataset belonging to Organization B via the API.
