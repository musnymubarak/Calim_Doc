import { useRef } from "react";

interface Props {
  /** Called with the horizontal delta (px) since the last move event while dragging. */
  onResize: (deltaX: number) => void;
  /** Optional class for positioning/margins. */
  className?: string;
  "aria-label"?: string;
}

/** A thin vertical divider the user can drag left/right to resize adjacent flex containers. */
export function ResizeHandle({ onResize, className, ...rest }: Props) {
  const lastX = useRef(0);

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    e.preventDefault();
    lastX.current = e.clientX;

    function move(ev: PointerEvent) {
      onResize(ev.clientX - lastX.current);
      lastX.current = ev.clientX;
    }
    function up() {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  return (
    <div
      className={`resize-handle ${className ?? ""}`}
      role="separator"
      aria-orientation="vertical"
      onPointerDown={onPointerDown}
      {...rest}
    />
  );
}
