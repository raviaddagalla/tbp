"use client";

import React, { useEffect, useState } from "react";

import { authedUrl } from "@/lib/api";

/** Resolve an authed media URL (short-lived token) asynchronously. */
export function useMediaUrl(path: string): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    authedUrl(path).then((u) => {
      if (alive) setUrl(u);
    });
    return () => {
      alive = false;
    };
  }, [path]);
  return url;
}

/** <img> that resolves its own short-lived media token. */
export function MediaImg({ path, ...props }: { path: string } & React.ImgHTMLAttributes<HTMLImageElement>) {
  const url = useMediaUrl(path);
  if (!url) return <div className={props.className} style={props.style} />;
  return <img src={url} alt="" {...props} />;
}
