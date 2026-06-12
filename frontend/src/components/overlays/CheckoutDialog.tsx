"use client";

import { BadgeCheck, CreditCard } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { api, ApiError } from "@/lib/api";
import { formatMoneyIn, useMoney } from "@/lib/format";
import { cartTotal, useCartStore } from "@/stores/cartStore";
import { useCurrencyStore } from "@/stores/currencyStore";
import { useUiStore } from "@/stores/uiStore";
import type { OrderResponse } from "@/types/api";

export function CheckoutDialog() {
  const open = useUiStore((s) => s.checkoutOpen);
  const setSheet = useUiStore((s) => s.setSheet);
  const lines = useCartStore((s) => s.lines);
  const clearCart = useCartStore((s) => s.clear);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [order, setOrder] = useState<OrderResponse | null>(null);

  const money = useMoney();
  const total = cartTotal(lines);
  const emailValid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email);
  const close = () => {
    setSheet("checkoutOpen", false);
    setOrder(null);
    setError(null);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.checkout(
        lines.map((l) => ({ product_id: l.product.id, qty: l.qty })),
        { name: name.trim(), email: email.trim() },
        useCurrencyStore.getState().currency,
      );
      setOrder(res);
      clearCart();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Checkout failed - please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={close} title={order ? "Order confirmed" : "Checkout"}>
      {order ? (
        <div className="space-y-4 text-center">
          <BadgeCheck className="mx-auto h-12 w-12 text-success" />
          <div>
            <p className="text-base font-bold">Thanks, your mock order is in!</p>
            <p className="mt-1 text-xs text-ink-soft">
              Order <span className="font-mono font-semibold">{order.order_id}</span> ·{" "}
              {/* the order keeps the currency it was placed in */}
              {formatMoneyIn(order.display_total, order.currency, 1)} · arrives in ~{order.eta_days} days
            </p>
          </div>
          <ul className="divide-y divide-line rounded-lg border border-line text-left">
            {order.lines.map((line) => (
              <li key={line.product_id} className="flex justify-between gap-2 p-2.5 text-xs">
                <span className="min-w-0 truncate">
                  {line.qty} × {line.name}
                </span>
                <span className="font-semibold">{money(line.unit_price * line.qty)}</span>
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-ink-faint">This is a demo checkout - no payment was taken.</p>
          <Button onClick={close} className="w-full">
            Back to planning
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg bg-surface-2/70 p-3 text-sm">
            <div className="flex justify-between font-semibold">
              <span>
                {lines.length} product{lines.length !== 1 ? "s" : ""}
              </span>
              <span>{money(total)}</span>
            </div>
            <p className="mt-0.5 text-[11px] text-ink-soft">Free delivery · mock payment</p>
          </div>
          <label className="block text-xs font-medium text-ink-soft">
            Full name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 block w-full rounded-md border border-line bg-surface px-3 py-2.5 text-sm"
              placeholder="Asha Sharma"
              autoComplete="name"
            />
          </label>
          <label className="block text-xs font-medium text-ink-soft">
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 block w-full rounded-md border border-line bg-surface px-3 py-2.5 text-sm"
              placeholder="asha@example.com"
              autoComplete="email"
            />
            {email && !emailValid && <span className="mt-1 block text-[11px] text-danger">Enter a valid email.</span>}
          </label>
          {error && <p className="rounded-md bg-danger-soft p-2.5 text-xs text-danger">{error}</p>}
          <Button
            onClick={() => void submit()}
            loading={busy}
            disabled={lines.length === 0 || !name.trim() || !emailValid}
            className="w-full"
            size="lg"
          >
            {!busy && <CreditCard className="h-4 w-4" />}
            Place mock order · {money(total)}
          </Button>
        </div>
      )}
    </Dialog>
  );
}
