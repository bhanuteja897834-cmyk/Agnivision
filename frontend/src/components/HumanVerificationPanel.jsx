import React, { useState, useEffect } from "react";

const CLASSIFICATION_OPTIONS = [
  {
    key: "ACTIVE_FIRE",
    icon: "🔥",
    name: "Active Fire",
    description: "Confirm active fire",
    color: "#dc2626",
    bg: "#fef2f2"
  },
  {
    key: "INDUSTRIAL_HEAT",
    icon: "🏭",
    name: "Industrial Heat",
    description: "Process / facility heat",
    color: "#ea580c",
    bg: "#fff7ed"
  },
  {
    key: "AGRICULTURAL_BURNING",
    icon: "🌾",
    name: "Agricultural Burning",
    description: "Crop/residue burn",
    color: "#ca8a04",
    bg: "#fefce8"
  },
  {
    key: "WILDLAND_FIRE",
    icon: "🌲",
    name: "Wildland Fire",
    description: "Forest/vegetation fire",
    color: "#16a34a",
    bg: "#f0fdf4"
  },
  {
    key: "UNKNOWN",
    icon: "❔",
    name: "Unknown",
    description: "Insufficient evidence",
    color: "#64748b",
    bg: "#f8fafc"
  }
];

export default function HumanVerificationPanel({
  selectedFire,
  assets,
  onVerify,
  verifying = false,
  verifiedLabel = null,
  verificationMessage = ""
}) {
  const [selectedChoice, setSelectedChoice] = useState(verifiedLabel || null);

  // Sync choice when verifiedLabel changes externally
  useEffect(() => {
    if (verifiedLabel) {
      setSelectedChoice(verifiedLabel);
    }
  }, [verifiedLabel]);

  // Reset or initialize choice when selectedFire changes
  useEffect(() => {
    setSelectedChoice(verifiedLabel || null);
  }, [selectedFire?.latitude, selectedFire?.longitude, verifiedLabel]);

  const activeOption = CLASSIFICATION_OPTIONS.find(
    (opt) => opt.key === selectedChoice
  );

  const nearestFacility = assets?.assets?.find(
    (a) => a?.type === "industrial" || a?.type === "power"
  );

  const facilityContextText = nearestFacility
    ? `${nearestFacility.name || "Industrial Facility"} (${nearestFacility.type})`
    : assets?.counts?.industrial > 0
      ? `${assets.counts.industrial} industrial facilities within 5km`
      : "No mapped industrial facilities within 5km";

  const handleConfirm = () => {
    if (!selectedChoice || verifying) return;
    if (onVerify) {
      onVerify(selectedChoice);
    }
  };

  return (
    <section className="inspection-section human-verification-redesign">
      <div className="section-title">
        <span>HUMAN VERIFICATION</span>
        <small>Operator Decision</small>
      </div>

      <div className="verification-panel-card">
        <p className="verification-lead">
          Select a verified classification based on satellite thermal signatures, spatial context, and infrastructure evidence.
        </p>

        {/* Visual Selectable Classification Cards */}
        <div className="operator-classification-grid" role="radiogroup" aria-label="Operator classification choices">
          {CLASSIFICATION_OPTIONS.map((opt) => {
            const isSelected = selectedChoice === opt.key;
            return (
              <div
                key={opt.key}
                role="radio"
                tabIndex={0}
                aria-checked={isSelected}
                className={`classification-choice-card ${isSelected ? "selected" : ""}`}
                onClick={() => setSelectedChoice(opt.key)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelectedChoice(opt.key);
                  }
                }}
              >
                <div className="card-top-indicator">
                  <span className="choice-icon">{opt.icon}</span>
                  <span className={`choice-radio-dot ${isSelected ? "checked" : ""}`} />
                </div>
                <strong className="choice-name">{opt.name}</strong>
                <span className="choice-desc">{opt.description}</span>
              </div>
            );
          })}
        </div>

        {/* Evidence Review Summary */}
        <div className="verification-review-summary">
          <div className="review-summary-title">
            <span>REVIEW SUMMARY</span>
            {activeOption ? (
              <span
                className="selected-choice-tag"
                style={{
                  color: activeOption.color,
                  backgroundColor: activeOption.bg,
                  borderColor: activeOption.color
                }}
              >
                {activeOption.icon} {activeOption.name} Selected
              </span>
            ) : (
              <span className="awaiting-choice-tag">Select a classification card above</span>
            )}
          </div>

          <div className="review-evidence-grid">
            <div className="evidence-row">
              <span className="evidence-label">Coordinates:</span>
              <strong className="evidence-val">
                {Number(selectedFire?.latitude).toFixed(5)}, {Number(selectedFire?.longitude).toFixed(5)}
              </strong>
            </div>

            <div className="evidence-row">
              <span className="evidence-label">Risk Level:</span>
              <strong className="evidence-val">
                {selectedFire?.risk_level || "Low"} ({selectedFire?.risk_score ?? 0}/100)
              </strong>
            </div>

            <div className="evidence-row">
              <span className="evidence-label">FRP:</span>
              <strong className="evidence-val">
                {selectedFire?.frp !== undefined ? `${selectedFire.frp} MW` : "N/A"}
              </strong>
            </div>

            <div className="evidence-row">
              <span className="evidence-label">Brightness:</span>
              <strong className="evidence-val">
                {selectedFire?.bright_ti4 ?? selectedFire?.brightness ?? "N/A"} K
              </strong>
            </div>

            <div className="evidence-row">
              <span className="evidence-label">Domain:</span>
              <strong className="evidence-val">
                {selectedFire?.geographic_validation?.domain || "LAND"} (
                {selectedFire?.geographic_validation?.state || "Not applicable"})
              </strong>
            </div>

            <div className="evidence-row">
              <span className="evidence-label">Facility Context:</span>
              <strong className="evidence-val">{facilityContextText}</strong>
            </div>
          </div>
        </div>

        {/* Confirm Action Button */}
        <div className="verification-action-bar">
          <button
            type="button"
            className="confirm-verification-btn"
            disabled={!selectedChoice || verifying}
            onClick={handleConfirm}
          >
            {verifying ? (
              <span>Saving verification to dataset…</span>
            ) : (
              <span>✓ CONFIRM HUMAN VERIFICATION</span>
            )}
          </button>
        </div>

        {/* Feedback Banners */}
        {verifiedLabel && !verifying && (
          <div className="verification-success-alert">
            <div className="alert-head">
              <strong>✓ Verification Saved</strong>
              <small>Human Verification Recorded</small>
            </div>
            <p>
              Classified as <strong>{verifiedLabel.replaceAll("_", " ")}</strong>. {verificationMessage}
            </p>
          </div>
        )}

        {!verifiedLabel && verificationMessage && (
          <div className="verification-error-alert">{verificationMessage}</div>
        )}
      </div>
    </section>
  );
}

