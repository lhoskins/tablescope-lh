import React from 'react';
import PropTypes from 'prop-types';
import { PageHeader } from '@/components/PageHeader';
import MFASettings from '@/components/users/MFASettings';
import { currentUser } from '@/services/auth';

export default class MFASettingsPage extends React.Component {
  static propTypes = {
    userId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  };

  static defaultProps = {
    userId: null,
  };

  render() {
    const userId = this.props.userId || currentUser.id;

    return (
      <div className="container">
        <PageHeader title="Multi-Factor Authentication Settings" />
        <div className="row">
          <div className="col-md-8 col-md-offset-2">
            <MFASettings userId={parseInt(userId, 10)} />
          </div>
        </div>
      </div>
    );
  }
}
