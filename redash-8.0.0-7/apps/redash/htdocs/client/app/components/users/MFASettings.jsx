import React, { Fragment } from 'react';
import PropTypes from 'prop-types';
import { Alert, Button, Card, Form, Input, Modal, Statistic, Tag } from 'antd';
import { SafetyOutlined, PhoneOutlined, KeyOutlined, WarningOutlined, DownloadOutlined } from '@ant-design/icons';
import { $http } from '@/services/ng';
import notification from '@/services/notification';

export default class MFASettings extends React.Component {
  static propTypes = {
    userId: PropTypes.number.isRequired,
  };

  constructor(props) {
    super(props);
    this.state = {
      loading: true,
      enrolled: false,
      required: false,
      phoneMasked: null,
      enrolledAt: null,
      lastUsedAt: null,
      backupCodesRemaining: 0,
      
      // Modal states
      changePhoneModalVisible: false,
      regenerateCodesModalVisible: false,
      verifyPhoneModalVisible: false,
      
      // Form states
      newPhoneNumber: '',
      verificationCode: '',
      password: '',
      
      // Loading states
      changingPhone: false,
      regeneratingCodes: false,
      verifyingPhone: false,
      
      // New backup codes
      newBackupCodes: [],
    };
  }

  componentDidMount() {
    this.loadMFASettings();
  }

  loadMFASettings = () => {
    this.setState({ loading: true });
    
    $http.get('api/auth/mfa/settings')
      .then(({ data }) => {
        // Log received response for debugging
        console.log('[MFA Settings] Received response:', data);
        
        // Validate that required fields are present
        if (typeof data.enrolled === 'undefined' || typeof data.required === 'undefined') {
          console.error('[MFA Settings] Invalid response structure - missing required fields:', data);
          throw new Error('Invalid response structure from server');
        }
        
        // Log the values we're about to set
        console.log('[MFA Settings] Setting state with:', {
          enrolled: data.enrolled,
          required: data.required,
          phoneMasked: data.phone_masked || null,
          enrolledAt: data.enrolled_at || null,
          lastUsedAt: data.last_used_at || null,
          backupCodesRemaining: data.backup_codes_remaining || 0,
        });
        
        // Update state with defensive null checks for optional fields
        this.setState({
          enrolled: data.enrolled,
          required: data.required,
          phoneMasked: data.phone_masked || null,
          enrolledAt: data.enrolled_at || null,
          lastUsedAt: data.last_used_at || null,
          backupCodesRemaining: data.backup_codes_remaining || 0,
          loading: false,
        }, () => {
          console.log('[MFA Settings] State updated successfully, current state:', this.state);
        });
      })
      .catch((error) => {
        console.error('[MFA Settings] Error loading settings:', error);
        console.error('[MFA Settings] Error response:', error.response);
        console.error('[MFA Settings] Error data:', error.data);
        
        const errorMessage = error.data?.message || error.data?.error || 'Unknown error';
        notification.error('Failed to load MFA settings', errorMessage);
        this.setState({ loading: false });
      });
  };

  showChangePhoneModal = () => {
    this.setState({
      changePhoneModalVisible: true,
      newPhoneNumber: '',
      password: '',
    });
  };

  hideChangePhoneModal = () => {
    this.setState({
      changePhoneModalVisible: false,
      newPhoneNumber: '',
      password: '',
    });
  };

  handleChangePhone = () => {
    const { newPhoneNumber, password } = this.state;
    
    if (!newPhoneNumber || !password) {
      notification.error('Phone number and password are required');
      return;
    }

    this.setState({ changingPhone: true });

    $http.put('api/auth/mfa/settings', {
      phone_number: newPhoneNumber,
      password: password,
    })
      .then(({ data }) => {
        notification.success(data.message || 'Verification code sent to new number');
        this.setState({
          changePhoneModalVisible: false,
          verifyPhoneModalVisible: true,
          changingPhone: false,
          password: '',
        });
      })
      .catch((error) => {
        // Log full error details for debugging
        console.error('[MFA Settings] Error updating phone number:', error);
        console.error('[MFA Settings] Error response:', error.response);
        console.error('[MFA Settings] Error data:', error.data);
        console.error('[MFA Settings] Error object:', error);
        
        // Extract error message from multiple possible locations
        const errorMessage = error.data?.message || error.data?.error || error.message || 'Unknown error';
        
        // Display user-friendly error message
        notification.error('Failed to update phone number', errorMessage);
        this.setState({ changingPhone: false });
      });
  };

  handleVerifyPhone = () => {
    const { verificationCode } = this.state;
    
    if (!verificationCode || verificationCode.length !== 6) {
      notification.error('Please enter a valid 6-digit code');
      return;
    }

    this.setState({ verifyingPhone: true });

    $http.post('api/auth/mfa/enroll/verify', {
      otp: verificationCode,
    })
      .then(() => {
        notification.success('Phone number updated successfully');
        this.setState({
          verifyPhoneModalVisible: false,
          verifyingPhone: false,
          verificationCode: '',
          newPhoneNumber: '',
        });
        this.loadMFASettings();
      })
      .catch((error) => {
        // Log full error details for debugging
        console.error('[MFA Settings] Error verifying phone:', error);
        console.error('[MFA Settings] Error response:', error.response);
        console.error('[MFA Settings] Error data:', error.data);
        console.error('[MFA Settings] Error object:', error);
        
        // Extract error message from multiple possible locations
        const errorMessage = error.data?.message || error.data?.error || error.message || 'Invalid code';
        
        // Display user-friendly error message
        notification.error('Verification failed', errorMessage);
        this.setState({ verifyingPhone: false });
      });
  };

  showRegenerateCodesModal = () => {
    this.setState({
      regenerateCodesModalVisible: true,
      password: '',
      newBackupCodes: [],
    });
  };

  hideRegenerateCodesModal = () => {
    this.setState({
      regenerateCodesModalVisible: false,
      password: '',
      newBackupCodes: [],
    });
  };

  handleRegenerateCodes = () => {
    const { password } = this.state;
    
    if (!password) {
      notification.error('Password is required');
      return;
    }

    this.setState({ regeneratingCodes: true });

    $http.post('api/auth/mfa/backup-codes', {
      password: password,
    })
      .then(({ data }) => {
        notification.success(data.message || 'New backup codes generated');
        this.setState({
          regeneratingCodes: false,
          newBackupCodes: data.backup_codes,
          password: '',
        });
        this.loadMFASettings();
      })
      .catch((error) => {
        // Log full error details for debugging
        console.error('[MFA Settings] Error regenerating backup codes:', error);
        console.error('[MFA Settings] Error response:', error.response);
        console.error('[MFA Settings] Error data:', error.data);
        console.error('[MFA Settings] Error object:', error);
        
        // Extract error message from multiple possible locations
        const errorMessage = error.data?.message || error.data?.error || error.message || 'Unknown error';
        
        // Display user-friendly error message
        notification.error('Failed to regenerate codes', errorMessage);
        this.setState({ regeneratingCodes: false });
      });
  };

  downloadBackupCodes = () => {
    const { newBackupCodes } = this.state;
    const content = newBackupCodes.join('\n');
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'tablescope-backup-codes.txt';
    a.click();
    URL.revokeObjectURL(url);
    notification.success('Backup codes downloaded');
  };

  renderMFAStatus() {
    const { enrolled, required, phoneMasked, enrolledAt, lastUsedAt } = this.state;

    if (!enrolled && !required) {
      return (
        <Alert
          message="MFA Not Required"
          description="Multi-factor authentication is not required for your account role."
          type="info"
          showIcon
          icon={<SafetyOutlined />}
        />
      );
    }

    if (!enrolled && required) {
      return (
        <Alert
          message="MFA Required"
          description="Your account requires multi-factor authentication. Please complete enrollment to access privileged features."
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          action={
            <Button type="primary" size="small" href="/mfa/enroll">
              Enroll Now
            </Button>
          }
        />
      );
    }

    return (
      <Card size="small" className="m-b-15">
        <div className="d-flex align-items-center">
          <SafetyOutlined style={{ fontSize: '24px', color: '#52c41a', marginRight: '12px' }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 'bold', marginBottom: '4px' }}>
              MFA Enabled
            </div>
            {phoneMasked && (
              <div style={{ fontSize: '12px', color: '#8c8c8c' }}>
                Phone: {phoneMasked}
              </div>
            )}
            {lastUsedAt && (
              <div style={{ fontSize: '12px', color: '#8c8c8c' }}>
                Last used: {new Date(lastUsedAt).toLocaleDateString()}
              </div>
            )}
          </div>
          <Tag color="success">Active</Tag>
        </div>
      </Card>
    );
  }

  renderBackupCodesStatus() {
    const { backupCodesRemaining } = this.state;
    const isLow = backupCodesRemaining < 3;

    return (
      <Card size="small" className="m-b-15">
        <div className="d-flex align-items-center">
          <KeyOutlined style={{ fontSize: '24px', color: isLow ? '#faad14' : '#1890ff', marginRight: '12px' }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 'bold', marginBottom: '4px' }}>
              Backup Codes
            </div>
            <div style={{ fontSize: '12px', color: '#8c8c8c' }}>
              {backupCodesRemaining} codes remaining
            </div>
            {isLow && (
              <div style={{ fontSize: '12px', color: '#faad14', marginTop: '4px' }}>
                <WarningOutlined />{' '}Low backup codes - consider regenerating
              </div>
            )}
          </div>
          {isLow && <Tag color="warning">Low</Tag>}
        </div>
      </Card>
    );
  }

  renderChangePhoneModal() {
    const { changePhoneModalVisible, newPhoneNumber, password, changingPhone } = this.state;

    return (
      <Modal
        title="Change Phone Number"
        visible={changePhoneModalVisible}
        onCancel={this.hideChangePhoneModal}
        footer={null}
        destroyOnClose
      >
        <Alert
          message="Verification Required"
          description="You'll need to verify your new phone number by entering a code sent via SMS."
          type="info"
          showIcon
          className="m-b-15"
        />

        <Form layout="vertical">
          <Form.Item label="New Phone Number" required>
            <Input
              prefix={<PhoneOutlined />}
              placeholder="+1234567890"
              value={newPhoneNumber}
              onChange={e => this.setState({ newPhoneNumber: e.target.value })}
              disabled={changingPhone}
            />
            <small style={{ color: '#8c8c8c' }}>
              Enter phone number in international format (e.g., +1234567890)
            </small>
          </Form.Item>

          <Form.Item label="Current Password" required>
            <Input.Password
              placeholder="Enter your password"
              value={password}
              onChange={e => this.setState({ password: e.target.value })}
              disabled={changingPhone}
            />
          </Form.Item>

          <Form.Item className="m-b-0">
            <Button
              type="primary"
              onClick={this.handleChangePhone}
              loading={changingPhone}
              disabled={!newPhoneNumber || !password}
              block
            >
              Send Verification Code
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    );
  }

  renderVerifyPhoneModal() {
    const { verifyPhoneModalVisible, verificationCode, verifyingPhone, newPhoneNumber } = this.state;

    return (
      <Modal
        title="Verify New Phone Number"
        visible={verifyPhoneModalVisible}
        onCancel={() => this.setState({ verifyPhoneModalVisible: false })}
        footer={null}
        destroyOnClose
      >
        <p>
          Enter the 6-digit code sent to <strong>{newPhoneNumber || 'your phone'}</strong>
        </p>

        <Form layout="vertical">
          <Form.Item label="Verification Code" required>
            <Input
              placeholder="000000"
              value={verificationCode}
              onChange={e => this.setState({ verificationCode: e.target.value.replace(/\D/g, '') })}
              maxLength={6}
              disabled={verifyingPhone}
              style={{ fontSize: '24px', textAlign: 'center', letterSpacing: '8px' }}
            />
          </Form.Item>

          <Form.Item className="m-b-0">
            <Button
              type="primary"
              onClick={this.handleVerifyPhone}
              loading={verifyingPhone}
              disabled={verificationCode.length !== 6}
              block
            >
              Verify Code
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    );
  }

  renderRegenerateCodesModal() {
    const { regenerateCodesModalVisible, password, regeneratingCodes, newBackupCodes } = this.state;

    if (newBackupCodes.length > 0) {
      return (
        <Modal
          title="New Backup Codes"
          visible={regenerateCodesModalVisible}
          onCancel={this.hideRegenerateCodesModal}
          footer={null}
          destroyOnClose
          width={600}
        >
          <Alert
            message="Important: Save these codes in a secure location"
            description="You can use these codes to access your account if you lose your phone. Each code can only be used once. Your old codes are no longer valid."
            type="warning"
            showIcon
            className="m-b-20"
          />

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: '10px',
            marginBottom: '20px',
          }}>
            {newBackupCodes.map((code, idx) => (
              <div
                key={idx}
                style={{
                  padding: '12px',
                  backgroundColor: '#f5f5f5',
                  borderRadius: '4px',
                  fontFamily: 'monospace',
                  fontSize: '16px',
                  textAlign: 'center',
                  fontWeight: 'bold',
                }}
              >
                {code}
              </div>
            ))}
          </div>

          <Button
            icon={<DownloadOutlined />}
            onClick={this.downloadBackupCodes}
            size="large"
            block
            className="m-b-10"
          >
            Download Codes
          </Button>

          <Button
            type="primary"
            onClick={this.hideRegenerateCodesModal}
            size="large"
            block
          >
            I've Saved My Codes
          </Button>
        </Modal>
      );
    }

    return (
      <Modal
        title="Regenerate Backup Codes"
        visible={regenerateCodesModalVisible}
        onCancel={this.hideRegenerateCodesModal}
        footer={null}
        destroyOnClose
      >
        <Alert
          message="Warning: Old codes will be invalidated"
          description="Generating new backup codes will permanently invalidate all your existing codes. Make sure you want to proceed."
          type="warning"
          showIcon
          className="m-b-15"
        />

        <Form layout="vertical">
          <Form.Item label="Current Password" required>
            <Input.Password
              placeholder="Enter your password"
              value={password}
              onChange={e => this.setState({ password: e.target.value })}
              disabled={regeneratingCodes}
            />
          </Form.Item>

          <Form.Item className="m-b-0">
            <Button
              type="primary"
              onClick={this.handleRegenerateCodes}
              loading={regeneratingCodes}
              disabled={!password}
              block
            >
              Generate New Codes
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    );
  }

  render() {
    const { loading, enrolled } = this.state;

    if (loading) {
      return <div>Loading MFA settings...</div>;
    }

    if (!enrolled) {
      return this.renderMFAStatus();
    }

    return (
      <div>
        <h5>Multi-Factor Authentication</h5>
        
        {this.renderMFAStatus()}
        {this.renderBackupCodesStatus()}

        <div className="button-group">
          <Button
            icon={<PhoneOutlined />}
            onClick={this.showChangePhoneModal}
            block
            className="m-b-10"
          >
            Change Phone Number
          </Button>

          <Button
            icon={<KeyOutlined />}
            onClick={this.showRegenerateCodesModal}
            block
          >
            Regenerate Backup Codes
          </Button>
        </div>

        {this.renderChangePhoneModal()}
        {this.renderVerifyPhoneModal()}
        {this.renderRegenerateCodesModal()}
      </div>
    );
  }
}
