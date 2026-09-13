import { useState } from 'react'
import { checkoutRecord, exchangePublicToken, openPlaidLink } from '../lib/plaid'
import type { CheckoutResponse } from '../lib/plaid'

const CHECKOUT_AMOUNT = 42.0

type Status = 'idle' | 'connecting' | 'processing' | 'paid' | 'error'

export default function Checkout() {
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<string | null>(null)
  const [payment, setPayment] = useState<CheckoutResponse | null>(null)

  async function handleSuccess(publicToken: string) {
    setStatus('processing')
    setError(null)
    try {
      const exchanged = await exchangePublicToken(publicToken)
      const result = await checkoutRecord(exchanged.access_token, CHECKOUT_AMOUNT)
      setPayment(result)
      setStatus('paid')
    } catch (e) {
      setError(String(e))
      setStatus('error')
    }
  }

  function start(): void {
    setStatus('connecting')
    setError(null)
    openPlaidLink({
      onSuccess: handleSuccess,
      onExit: () => setStatus('idle'),
    }).catch((e: unknown) => {
      setError(String(e))
      setStatus('error')
    })
  }

  if (status === 'paid' && payment) {
    return (
      <span className="checkout paid" title={`Payment ${payment.payment_id}`}>
        Paid {payment.amount.toFixed(2)} {payment.currency}
      </span>
    )
  }

  return (
    <span className="checkout">
      {status === 'error' && error && <span className="checkout-error">{error}</span>}
      <button onClick={start} disabled={status === 'connecting' || status === 'processing'}>
        {status === 'connecting' || status === 'processing' ? 'Connecting…' : 'Pay with bank'}
      </button>
    </span>
  )
}