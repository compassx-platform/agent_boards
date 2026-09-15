import { useState } from 'react'
import { CreditCard, CheckCircle2, RotateCw, AlertCircle } from 'lucide-react'
import { checkoutRecord, exchangePublicToken, openPlaidLink } from '../lib/plaid'
import type { CheckoutResponse } from '../lib/plaid'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

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
      <Badge
        variant="outline"
        className="border-emerald-500/40 text-emerald-400 bg-emerald-500/10 font-mono text-xs gap-1.5 px-2 py-1"
        title={`Payment ID: ${payment.payment_id}`}
      >
        <CheckCircle2 className="size-3.5" />
        Paid ${payment.amount.toFixed(2)} {payment.currency}
      </Badge>
    )
  }

  return (
    <div className="flex items-center gap-2">
      {status === 'error' && error && (
        <span className="text-xs text-destructive flex items-center gap-1">
          <AlertCircle className="size-3" />
          {error}
        </span>
      )}
      <Button
        variant="outline"
        size="sm"
        onClick={start}
        disabled={status === 'connecting' || status === 'processing'}
        className="gap-1.5 text-xs h-7"
      >
        {status === 'connecting' || status === 'processing' ? (
          <RotateCw className="size-3 animate-spin" />
        ) : (
          <CreditCard className="size-3 text-muted-foreground" />
        )}
        {status === 'connecting' || status === 'processing' ? 'Connecting…' : 'Bank Pay'}
      </Button>
    </div>
  )
}