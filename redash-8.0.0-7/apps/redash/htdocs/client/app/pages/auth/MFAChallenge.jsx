import React, { useState } from "react";
import ReactDOM from "react-dom";
import PropTypes from "prop-types";
import { Alert, Button, Input, Tabs } from "antd";
import "./MFAChallenge.less";

const { TabPane } = Tabs;

function MFAChallenge({ orgSlug, tempToken, phoneLast4 }) {
  const [activeTab, setActiveTab] = useState("otp");
  const [otp, setOtp] = useState("");
  const [backupCode, setBackupCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [warning, setWarning] = useState(null);
  const [success, setSuccess] = useState(null);
  const [resendLoading, setResendLoading] = useState(false);
  const [smsSent, setSmsSent] = useState(true); // Show initial SMS confirmation

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    setWarning(null);
    setSuccess(null);

    const payload = {
      temp_token: tempToken,
      ...(activeTab === "otp" ? { otp } : { backup_code: backupCode }),
    };

    try {
      const response = await fetch(`/api/auth/mfa/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await response.json();

      if (response.ok) {
        // Show success message before redirect (Requirement 11.7)
        setSuccess("Verification successful! Redirecting...");
        
        if (data.warning) {
          setWarning(data.warning);
        }
        
        // Redirect after showing success message
        const redirectUrl = data.redirect || (orgSlug ? `/${orgSlug}` : "/");
        setTimeout(() => {
          window.location.href = redirectUrl;
        }, 1500);
      } else {
        setError(data.error || "Verification failed");
      }
    } catch (err) {
      setError("Verification failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const requestNewCode = async () => {
    setResendLoading(true);
    setError(null);
    setSuccess(null);
    setSmsSent(false);

    try {
      const response = await fetch(`/api/auth/mfa/resend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ temp_token: tempToken }),
      });

      if (response.ok) {
        setError(null);
        setSuccess("New code sent to your phone"); // Requirement 11.3
        setSmsSent(true);
      } else {
        const data = await response.json();
        setError(data.error || "Failed to send new code");
      }
    } catch (err) {
      setError("Failed to send new code. Please try again.");
    } finally {
      setResendLoading(false);
    }
  };

  const renderOTPTab = () => (
    <div className="mfa-tab-content">
      <p className="mfa-description">
        Enter the 6-digit code sent to your phone ending in <strong>{phoneLast4}</strong>
      </p>

      {smsSent && !error && !success && (
        <Alert 
          type="info" 
          message="A verification code has been sent to your phone" 
          showIcon 
          className="m-b-15" 
        />
      )}

      <div className="form-group">
        <Input
          placeholder="000000"
          value={otp}
          onChange={e => setOtp(e.target.value.replace(/\D/g, ""))}
          maxLength={6}
          disabled={loading}
          size="large"
          autoFocus
          style={{ fontSize: "24px", textAlign: "center", letterSpacing: "8px" }}
          onPressEnter={() => otp.length === 6 && handleSubmit()}
        />
      </div>

      <Button
        type="primary"
        onClick={handleSubmit}
        loading={loading}
        disabled={otp.length !== 6}
        size="large"
        block
      >
        Verify
      </Button>

      <Button
        type="link"
        onClick={requestNewCode}
        disabled={loading || resendLoading}
        loading={resendLoading}
        block
        className="m-t-10"
      >
        Didn't receive a code? Send new code
      </Button>
    </div>
  );

  const renderBackupTab = () => (
    <div className="mfa-tab-content">
      <p className="mfa-description">
        Enter one of your 8-character backup codes
      </p>

      <Alert 
        type="warning" 
        message="Each backup code can only be used once" 
        description="After using a backup code, it will be permanently invalidated. Make sure you have access to your remaining codes."
        showIcon 
        className="m-b-15" 
      />

      <div className="form-group">
        <Input
          placeholder="XXXXXXXX"
          value={backupCode}
          onChange={e => setBackupCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
          maxLength={8}
          disabled={loading}
          size="large"
          style={{ fontSize: "20px", textAlign: "center", letterSpacing: "4px" }}
          onPressEnter={() => backupCode.length === 8 && handleSubmit()}
        />
      </div>

      <Button
        type="primary"
        onClick={handleSubmit}
        loading={loading}
        disabled={backupCode.length !== 8}
        size="large"
        block
      >
        Verify
      </Button>
    </div>
  );

  return (
    <div className="mfa-challenge-container">
      <h2>Two-Factor Authentication</h2>

      {error && <Alert type="error" message={error} showIcon className="m-b-15" />}
      {success && <Alert type="success" message={success} showIcon className="m-b-15" />}
      {warning && <Alert type="warning" message={warning} showIcon className="m-b-15" />}

      <Tabs activeKey={activeTab} onChange={setActiveTab} className="mfa-tabs">
        <TabPane tab="SMS Code" key="otp">
          {renderOTPTab()}
        </TabPane>
        <TabPane tab="Backup Code" key="backup">
          {renderBackupTab()}
        </TabPane>
      </Tabs>
    </div>
  );
}

MFAChallenge.propTypes = {
  orgSlug: PropTypes.string,
  tempToken: PropTypes.string.isRequired,
  phoneLast4: PropTypes.string.isRequired,
};

MFAChallenge.defaultProps = {
  orgSlug: null,
};

// Auto-initialize if root element exists
if (typeof document !== "undefined") {
  const rootElement = document.getElementById("mfa-challenge-root");
  if (rootElement) {
    const config = window.mfaChallengeConfig || {};
    ReactDOM.render(
      <MFAChallenge
        orgSlug={config.orgSlug}
        tempToken={config.tempToken}
        phoneLast4={config.phoneLast4}
      />,
      rootElement
    );
  }
}

export default MFAChallenge;
