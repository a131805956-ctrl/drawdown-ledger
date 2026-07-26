import { createDepthBands } from "./chartModel";

interface DepthBandsProps {
    depths?: readonly number[];
}

export function DepthBands({
    depths = [0.1, 0.2, 0.3, 0.4, 0.5],
}: DepthBandsProps) {
    const bands = createDepthBands(depths);
    const deepest = Math.abs(bands.at(-1)?.bottom ?? -0.5);

    return (
        <div className="depth-bands" aria-hidden="true">
            {bands.map((band) => {
                const top = (Math.abs(band.top) / deepest) * 100;
                const height =
                    ((Math.abs(band.bottom) - Math.abs(band.top)) / deepest) *
                    100;
                return (
                    <span
                        key={band.threshold}
                        className={`depth-band depth-band--${band.tone}`}
                        style={{ top: `${String(top)}%`, height: `${String(height)}%` }}
                    >
                        <small>{band.label}</small>
                    </span>
                );
            })}
        </div>
    );
}
