import { useCurrencyStore } from "@/stores/currencyStore";

const formatters = new Map<string, Intl.NumberFormat>();

function formatterFor(code: string): Intl.NumberFormat {
  let fmt = formatters.get(code);
  if (!fmt) {
    fmt = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
      maximumFractionDigits: 0,
    });
    formatters.set(code, fmt);
  }
  return fmt;
}

/** Format a BASE-currency amount in an explicit display currency. */
export function formatMoneyIn(baseAmount: number, code: string, rate: number): string {
  return formatterFor(code).format(Math.round(baseAmount * rate));
}

/** Reactive money formatter bound to the selected currency (SAR/USD). */
export function useMoney(): (baseAmount: number) => string {
  const currency = useCurrencyStore((s) => s.currency);
  const rates = useCurrencyStore((s) => s.config.rates);
  const rate = rates[currency] ?? 1.0;
  return (baseAmount: number) => formatMoneyIn(baseAmount, currency, rate);
}

/** Non-reactive variant for code outside components (toasts etc.). */
export function formatMoney(baseAmount: number): string {
  const { currency, config } = useCurrencyStore.getState();
  return formatMoneyIn(baseAmount, currency, config.rates[currency] ?? 1.0);
}

export function formatCm(cm: number): string {
  return cm >= 100 ? `${(cm / 100).toFixed(cm % 100 === 0 ? 0 : 1)} m` : `${Math.round(cm)} cm`;
}

export function formatDims(w: number, d: number, h?: number): string {
  const base = `${Math.round(w)} × ${Math.round(d)}`;
  return h ? `${base} × ${Math.round(h)} cm` : `${base} cm`;
}

/** Mockup-style labelled dimensions: "220W × 95D × 85H cm". */
export function formatDimsLabelled(w: number, d: number, h: number): string {
  return `${Math.round(w)}W × ${Math.round(d)}D × ${Math.round(h)}H cm`;
}

export function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value));
}
