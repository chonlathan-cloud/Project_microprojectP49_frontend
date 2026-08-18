import Image from "next/image";

export function ServiceArtwork({ serviceId, imageVersion }: { serviceId: string; imageVersion?: string | null }) {
  if (!imageVersion) return <div className="service-media service-media-placeholder" aria-hidden="true" />;

  const src = `/api/spa/api/v1/public/services/${encodeURIComponent(serviceId)}/image?v=${encodeURIComponent(imageVersion)}`;
  return <div className="service-media" aria-hidden="true"><Image src={src} alt="" fill unoptimized sizes="(max-width: 700px) calc(100vw - 32px), (max-width: 1023px) 50vw, 33vw" /></div>;
}
