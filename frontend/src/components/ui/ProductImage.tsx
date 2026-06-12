"use client";

import { Armchair } from "lucide-react";
import { useState } from "react";
import { API_BASE } from "@/lib/constants";

/** Product photo with graceful fallback if the image fails to load. */
export function ProductImage({
  src,
  alt,
  className = "",
}: {
  src: string;
  alt: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const url = src.startsWith("http") ? src : `${API_BASE}${src}`;

  if (failed) {
    return (
      <div className={`flex items-center justify-center bg-beige-50 ${className}`} role="img" aria-label={alt}>
        <Armchair className="h-8 w-8 text-beige-200" aria-hidden />
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- backend-served images, fallback handled
    <img
      src={url}
      alt={alt}
      loading="lazy"
      className={`object-cover ${className}`}
      onError={() => setFailed(true)}
    />
  );
}
