import React from 'react';
import PropTypes from 'prop-types';
import Menu from 'antd/lib/menu';
import './SettingsSidebar.less';

/**
 * SettingsSidebar Component
 * 
 * Navigation sidebar for project settings sections.
 * Displays available settings categories and highlights the active section.
 */
function SettingsSidebar({ sections, activeSection, onSectionChange }) {
  const handleMenuClick = ({ key }) => {
    onSectionChange(key);
  };

  return (
    <div className="settings-sidebar">
      <Menu
        mode="inline"
        selectedKeys={[activeSection]}
        onClick={handleMenuClick}
        className="settings-menu"
      >
        {sections.map((section) => (
          <Menu.Item key={section.id} icon={section.icon && <i className={section.icon} />}>
            {section.label}
          </Menu.Item>
        ))}
      </Menu>
    </div>
  );
}

SettingsSidebar.propTypes = {
  sections: PropTypes.arrayOf(
    PropTypes.shape({
      id: PropTypes.string.isRequired,
      label: PropTypes.string.isRequired,
      icon: PropTypes.string,
      requiredPermission: PropTypes.string,
    })
  ).isRequired,
  activeSection: PropTypes.string.isRequired,
  onSectionChange: PropTypes.func.isRequired,
};

export default SettingsSidebar;
