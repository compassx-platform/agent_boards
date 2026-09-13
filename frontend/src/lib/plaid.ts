const PLAID_LINK_CDN = 'https://cdn.plaid.com/link/v2/stable/link-stable.min.js'

declare global {
  interface Window {
    Plaid?: {
      create: (config: PlaidCreateConfig) => PlaidHandler
    }
  }
}

export interface PlaidCreateConfig {
  token: string
  onSuccess: (publicToken: string, metadata: unknown) => void
  onExit?: (error: unknown, metadata: unknown) => void
  onEvent?: (eventName: string, metadata: unknown) => void
}

export interface PlaidHandler {
  open: () => void
  destroy: () => void
}

export interface PlaidAccount {
  account_id: string
  name: string
  mask: string | null
  type: string
  subtype: string | null
  bank_name: string | null
}

export interface PlaidLinkTokenResponse {
  status: string
  link_token: string
  environment: string
  mode: string
}

export interface PlaidExchangeResponse {
  status: string
  access_token: string
  item_id: string | null
  account: PlaidAccount
  mode: string
  plaid_account_id: string
}

export interface CheckoutResponse {
  status: string
  payment_id: string
  payment_status: string
  amount: number
  currency: string
  reference: string | null
}

async function post<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const json = (await res.json()) as { detail?: unknown }
      if (json.detail) detail = JSON.stringify(json.detail)
    } catch {
      // ignore non-JSON error bodies
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

let plaidFactory: Window['Plaid'] | null = null
let loader: Promise<Window['Plaid']> | null = null

function loadPlaid(): Promise<Window['Plaid']> {
  if (plaidFactory) return Promise.resolve(plaidFactory)
  if (loader) return loader
  loader = new Promise<Window['Plaid']>((resolve, reject) => {
    if (window.Plaid) {
      plaidFactory = window.Plaid
      resolve(window.Plaid)
      return
    }
    const script = document.createElement('script')
    script.src = PLAID_LINK_CDN
    script.async = true
    script.onload = () => {
      if (window.Plaid) {
        plaidFactory = window.Plaid
        resolve(window.Plaid)
      } else {
        reject(new Error('Plaid Link loaded but window.Plaid is unavailable'))
      }
    }
    script.onerror = () => reject(new Error('Failed to load Plaid Link'))
    document.head.appendChild(script)
  })
  return loader
}

export async function createLinkToken(
  options: { user?: string; client_name?: string } = {},
): Promise<PlaidLinkTokenResponse> {
  return post<PlaidLinkTokenResponse>('/payments/plaid/link_token', {
    user: options.user ?? '',
    client_name: options.client_name ?? 'TaskExec',
  })
}

export async function exchangePublicToken(publicToken: string): Promise<PlaidExchangeResponse> {
  return post<PlaidExchangeResponse>('/payments/plaid/exchange', { public_token: publicToken })
}

export async function checkoutRecord(
  accessToken: string,
  amount: number,
  currency = 'USD',
): Promise<CheckoutResponse> {
  return post<CheckoutResponse>('/payments/checkout', {
    access_token: accessToken,
    amount,
    currency,
  })
}

export async function openPlaidLink(options: {
  onSuccess: (publicToken: string) => void
  onExit?: (error: unknown, metadata: unknown) => void
  onEvent?: (eventName: string, metadata: unknown) => void
}): Promise<PlaidHandler> {
  const Plaid = await loadPlaid()
  const link = await createLinkToken()
  if (!Plaid) throw new Error('Plaid.js failed to load')
  const handler = Plaid.create({
    token: link.link_token,
    onSuccess: options.onSuccess,
    onExit: options.onExit,
    onEvent: options.onEvent,
  })
  handler.open()
  return handler
}