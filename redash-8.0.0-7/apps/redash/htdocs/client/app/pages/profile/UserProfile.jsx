import React, { useState, useEffect } from 'react';
import ReactDOM from 'react-dom';
import { Card, Button, Input, Form, Alert, Spin } from 'antd';
import { UserOutlined, MailOutlined, KeyOutlined, SafetyOutlined } from '@ant-design/icons';
import MFASettings from '@/components/users/MFASettings';
import './UserProfile.less';

function UserProfile() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadUserProfile();
  }, []);

  const loadUserProfile = async () => {
    try {
      const response = await fetch('/api/users/me');
      const data = await response.json();
      
      if (response.ok) {
        setUser(data);
      } else {
        setError('Failed to load user profile');
      }
    } catch (err) {
      setError('Failed to load user profile');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="user-profile-page">
        <div className="container">
          <Spin size="large" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="user-profile-page">
        <div className="container">
          <Alert message="Error" description={error} type="error" showIcon />
        </div>
      </div>
    );
  }

  return (
    <div className="user-profile-page">
      <div className="container">
        <div className="profile-header">
          <h1>My Profile</h1>
          <Button onClick={() => window.location.href = '/'}>Back to Home</Button>
        </div>

        <div className="profile-content">
          <Card title="Profile Information" className="profile-card">
            <Form layout="vertical">
              <Form.Item label="Name">
                <Input 
                  prefix={<UserOutlined />}
                  value={user?.name || ''}
                  disabled
                />
              </Form.Item>

              <Form.Item label="Email">
                <Input 
                  prefix={<MailOutlined />}
                  value={user?.email || ''}
                  disabled
                />
              </Form.Item>

              <Form.Item label="Groups">
                <div className="groups-list">
                  {user?.groups?.map(group => (
                    <span key={group} className="group-tag">{group}</span>
                  ))}
                </div>
              </Form.Item>
            </Form>
          </Card>

          <Card 
            title={
              <span>
                <SafetyOutlined /> Multi-Factor Authentication
              </span>
            } 
            className="mfa-card"
          >
            <MFASettings userId={user?.id} />
          </Card>
        </div>
      </div>
    </div>
  );
}

// Mount the component
const container = document.getElementById('react-root');
if (container) {
  ReactDOM.render(<UserProfile />, container);
}

export default UserProfile;
