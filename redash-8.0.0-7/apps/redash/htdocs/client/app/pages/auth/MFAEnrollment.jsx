import React, { useState } from "react";
import ReactDOM from "react-dom";
import PropTypes from "prop-types";
import { Alert, Button, Input, Steps } from "antd";
import "./MFAEnrollment.less";

const { Step } = Steps;

function MFAEnrollment({ orgSlug }) {
  const [currentStep, setCurrentStep] = useState(0); // 0: phone, 1: verify, 2: backup
  const [phoneNumber, setPhoneNumber] = useState("");
  const [otp, setOtp] = useState("");
  const [backupCodes, setBackupCodes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const handlePhoneSubmit = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/auth/mfa/enroll`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone_number: phoneNumber }),
      });

      const data = await response.json();

      if (response.ok) {
        setBackupCodes(data.backup_codes);
        setSuccess("Verification code sent to your phone");
        setCurrentStep(1);
      } else {
        setError(data.error || "Failed to enroll in MFA");
      }
    } catch (err) {
      setError("Failed to enroll in MFA. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleVerifySubmit = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/auth/mfa/verify-enrollment`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ otp }),
      });

      if (response.ok) {
        setSuccess("Phone number verified successfully");
        setCurrentStep(2);
      } else {
        const data = await response.json();
        setError(data.error || "Invalid verification code");
      }
    } catch (err) {
      setError("Failed to verify code. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const downloadBackupCodes = () => {
    const content = backupCodes.join("\n");
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "tablescope-backup-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleComplete = () => {
    const redirectUrl = orgSlug ? `/${orgSlug}` : "/";
    window.location.href = redirectUrl;
  };

  const renderPhoneStep = () => (
    <div className="mfa-step">
      <h2>Enable Two-Factor Authentication</h2>
      <p className="mfa-description">
        As a privileged user, you must enable MFA to access admin features.
        Enter your mobile phone number to receive verification codes.
      </p>

      {error && <Alert type="error" message={error} showIcon className="m-b-15" />}
      {success && <Alert type="success" message={success} showIcon className="m-b-15" />}

      <div className="form-group">
        <label htmlFor="phoneNumber">Phone Number</label>
        <Input
          id="phoneNumber"
          placeholder="+1234567890"
          value={phoneNumber}
          onChange={e => setPhoneNumber(e.target.value)}
          disabled={loading}
          size="large"
          className="m-b-10"
        />
        <small className="help-block">
          Enter your phone number in international format (e.g., +1234567890)
        </small>
      </div>

      <Button
        type="primary"
        onClick={handlePhoneSubmit}
        loading={loading}
        disabled={!phoneNumber || phoneNumber.length < 10}
        size="large"
        block
      >
        Send Verification Code
      </Button>
    </div>
  );

  const renderVerifyStep = () => (
    <div className="mfa-step">
      <h2>Verify Your Phone Number</h2>
      <p className="mfa-description">
        Enter the 6-digit code sent to <strong>{phoneNumber}</strong>
      </p>

      {error && <Alert type="error" message={error} showIcon className="m-b-15" />}
      {success && <Alert type="success" message={success} showIcon className="m-b-15" />}

      <div className="form-group">
        <label htmlFor="otp">Verification Code</label>
        <Input
          id="otp"
          placeholder="000000"
          value={otp}
          onChange={e => setOtp(e.target.value.replace(/\D/g, ""))}
          maxLength={6}
          disabled={loading}
          size="large"
          className="m-b-10"
          style={{ fontSize: "24px", textAlign: "center", letterSpacing: "8px" }}
        />
      </div>

      <Button
        type="primary"
        onClick={handleVerifySubmit}
        loading={loading}
        disabled={otp.length !== 6}
        size="large"
        block
      >
        Verify Code
      </Button>

      <Button
        type="link"
        onClick={() => setCurrentStep(0)}
        disabled={loading}
        block
        className="m-t-10"
      >
        Change Phone Number
      </Button>
    </div>
  );

  const renderBackupStep = () => (
    <div className="mfa-step">
      <h2>Save Your Backup Codes</h2>
      
      <Alert
        type="warning"
        message="Important: Save these codes in a secure location"
        description="You can use these codes to access your account if you lose your phone. Each code can only be used once."
        showIcon
        className="m-b-20"
      />

      <div className="backup-codes-container">
        {backupCodes.map((code, idx) => (
          <div key={idx} className="backup-code">
            {code}
          </div>
        ))}
      </div>

      <div className="button-group">
        <Button
          onClick={downloadBackupCodes}
          size="large"
          block
          className="m-b-10"
        >
          Download Codes
        </Button>

        <Button
          type="primary"
          onClick={handleComplete}
          size="large"
          block
        >
          I've Saved My Codes
        </Button>
      </div>
    </div>
  );

  return (
    <div className="mfa-enrollment-container">
      <Steps current={currentStep} className="m-b-30">
        <Step title="Phone Number" description="Enter your phone" />
        <Step title="Verify" description="Enter code" />
        <Step title="Backup Codes" description="Save codes" />
      </Steps>

      {currentStep === 0 && renderPhoneStep()}
      {currentStep === 1 && renderVerifyStep()}
      {currentStep === 2 && renderBackupStep()}
    </div>
  );
}

MFAEnrollment.propTypes = {
  orgSlug: PropTypes.string,
};

MFAEnrollment.defaultProps = {
  orgSlug: null,
};

// Auto-initialize if root element exists
if (typeof document !== "undefined") {
  const rootElement = document.getElementById("mfa-enrollment-root");
  if (rootElement) {
    const config = window.mfaEnrollmentConfig || {};
    ReactDOM.render(<MFAEnrollment orgSlug={config.orgSlug} />, rootElement);
  }
}

export default MFAEnrollment;
