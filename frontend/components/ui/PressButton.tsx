"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { T } from "@/lib/theme";

/**
 * The site's main action button: a bark pill that floods with ember from the
 * bottom on hover and dips slightly on press, so every click visibly lands.
 * It never goes `disabled` while work is running; callers queue the click
 * instead, because a button that silently ignores you feels broken.
 */
export function PressButton({
  children,
  busy,
  className = "",
  tone = "bark",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode; busy?: boolean; tone?: "bark" | "ember" }) {
  return (
    <button
      {...rest}
      aria-busy={busy || undefined}
      className={`group relative inline-flex select-none items-center justify-center gap-3 overflow-hidden rounded-[36px] px-7 py-[15px] text-[13px] font-medium uppercase transition-transform duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40 ${className}`}
      style={{ background: tone === "ember" ? T.ember : T.bark, color: T.cream, ...rest.style }}
    >
      <span
        aria-hidden
        className="absolute inset-0 origin-bottom scale-y-0 rounded-[36px] transition-transform duration-500 ease-[cubic-bezier(.2,.8,.2,1)] group-hover:scale-y-100 group-focus-visible:scale-y-100"
        style={{ background: tone === "ember" ? T.flame : T.ember }}
      />
      {busy && (
        <span aria-hidden className="relative h-2 w-2 animate-ping rounded-full" style={{ background: T.saffron }} />
      )}
      <span className="relative">{children}</span>
    </button>
  );
}
