import React, { useMemo } from "react";

export default function StateActivity({ fires = [] }) {
  const stateData = useMemo(() => {
    if (!fires || fires.length === 0) return [];

    const counts = {};
    let validStateTotal = 0;

    for (const f of fires) {
      const state = f?.geographic_validation?.state;
      // Ignore null, undefined, empty strings, "Not applicable", and "Unknown"
      if (
        !state ||
        state === "Not applicable" ||
        state.toLowerCase() === "unknown" ||
        state.toLowerCase() === "unresolved"
      ) {
        continue;
      }
      counts[state] = (counts[state] || 0) + 1;
      validStateTotal++;
    }

    const sortedStates = Object.entries(counts)
      .map(([state, count]) => ({
        state,
        count,
        pct: validStateTotal > 0 ? ((count / validStateTotal) * 100).toFixed(1) : "0"
      }))
      .sort((a, b) => b.count - a.count);

    return {
      states: sortedStates,
      totalClassified: validStateTotal
    };
  }, [fires]);

  const maxCount = stateData.states?.[0]?.count || 1;

  return (
    <div className="dashboard-panel state-activity-panel">
      <div className="panel-title-row">
        <div>
          <h3>Geographic Administrative Activity</h3>
          <p className="panel-subtitle">
            Indian state attribution resolved via Natural Earth 50m administrative boundaries
          </p>
        </div>
        <span className="source-pill">Natural Earth Admin-1</span>
      </div>

      {!stateData.states || stateData.states.length === 0 ? (
        <div className="panel-empty-state">
          No observations currently attributed to administrative states.
        </div>
      ) : (
        <div className="state-bars-container">
          <div className="state-summary-banner">
            <span>
              Attributed observations: <strong>{stateData.totalClassified}</strong>
            </span>
            <span>
              States active: <strong>{stateData.states.length}</strong>
            </span>
          </div>

          <div className="state-list">
            {stateData.states.map((item) => {
              const relativeBarWidth = ((item.count / maxCount) * 100).toFixed(1);
              return (
                <div key={item.state} className="state-row">
                  <div className="state-info">
                    <strong className="state-name">{item.state}</strong>
                    <span className="state-count-tag">
                      {item.count} events ({item.pct}%)
                    </span>
                  </div>

                  <div className="bar-track">
                    <div
                      className="bar-fill state-fill"
                      style={{ width: `${relativeBarWidth}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

