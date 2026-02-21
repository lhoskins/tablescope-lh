from six import python_2_unicode_compatible
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import relationship
from sqlalchemy_utils.models import generic_repr
from redash.settings.organization import settings as org_settings

from .base import db, Column
from .mixins import TimestampMixin
from .types import MutableDict, PseudoJSON
from .users import User, Group

@python_2_unicode_compatible
@generic_repr('id', 'name', 'slug')
class Organization(TimestampMixin, db.Model):
    SETTING_GOOGLE_APPS_DOMAINS = 'google_apps_domains'
    SETTING_IS_PUBLIC = "is_public"

    # Provisioning status constants
    PROVISIONING_STATUS_PENDING = 'pending'
    PROVISIONING_STATUS_IN_PROGRESS = 'in_progress'
    PROVISIONING_STATUS_COMPLETE = 'complete'
    PROVISIONING_STATUS_FAILED = 'failed'

    id = Column(db.Integer, primary_key=True)
    name = Column(db.String(255))
    slug = Column(db.String(255), unique=True)
    settings = Column(MutableDict.as_mutable(PseudoJSON))

    # Customer information fields
    address = Column(db.Text, nullable=True)  # Legacy field, kept for backward compatibility
    primary_contact_first_name = Column(db.String(255), nullable=True)
    primary_contact_last_name = Column(db.String(255), nullable=True)
    primary_contact_email = Column(db.String(255), nullable=True)
    primary_contact_user_id = Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    
    # Detailed customer information fields (added in migration 004)
    company_name = Column(db.String(255), nullable=True)
    address_line1 = Column(db.String(255), nullable=True)
    address_line2 = Column(db.String(255), nullable=True)
    city = Column(db.String(100), nullable=True)
    state_province = Column(db.String(100), nullable=True)
    postal_code = Column(db.String(20), nullable=True)
    country = Column(db.String(100), nullable=True)
    contact_phone = Column(db.String(50), nullable=True)
    organization_email = Column(db.String(255), nullable=True)

    # Provisioning status tracking
    provisioning_status = Column(db.String(50), default=PROVISIONING_STATUS_PENDING)
    provisioning_error = Column(db.Text, nullable=True)
    provisioned_at = Column(db.DateTime(True), nullable=True)

    groups = relationship("Group", lazy="dynamic")
    events = relationship("Event", lazy="dynamic", order_by="desc(Event.created_at)")

    # Relationship with Project
    projects = relationship("Project", back_populates="organization", cascade="all, delete-orphan", lazy="dynamic")

    # Relationship with DataSource
    data_sources = relationship("DataSource", back_populates="org", cascade="all, delete-orphan", lazy="dynamic")

    # Relationship with primary contact user
    primary_contact_user = relationship("User", foreign_keys=[primary_contact_user_id])

    __tablename__ = 'organizations'

    def __str__(self):
        return u'%s (%s)' % (self.name, self.id)

    @classmethod
    def get_by_slug(cls, slug):
        return cls.query.filter(cls.slug == slug).first()

    @classmethod
    def get_by_id(cls, _id):
        return cls.query.filter(cls.id == _id).one()

    @property
    def default_group(self):
        return self.groups.filter(Group.name == 'default', Group.type == Group.BUILTIN_GROUP).first()

    @property
    def google_apps_domains(self):
        return self.settings.get(self.SETTING_GOOGLE_APPS_DOMAINS, [])

    @property
    def is_public(self):
        return self.settings.get(self.SETTING_IS_PUBLIC, False)

    @property
    def is_disabled(self):
        return self.settings.get('is_disabled', False)

    def disable(self):
        self.settings['is_disabled'] = True

    def enable(self):
        self.settings['is_disabled'] = False

    def set_setting(self, key, value):
        if key not in org_settings:
            raise KeyError(key)

        self.settings.setdefault('settings', {})
        self.settings['settings'][key] = value
        flag_modified(self, 'settings')

    def get_setting(self, key, raise_on_missing=True):
        if key in self.settings.get('settings', {}):
            return self.settings['settings'][key]

        if key in org_settings:
            return org_settings[key]

        if raise_on_missing:
            raise KeyError(key)

        return None

    @property
    def admin_group(self):
        return self.groups.filter(Group.name == 'admin', Group.type == Group.BUILTIN_GROUP).first()

    def has_user(self, email):
        return self.users.filter(User.email == email).count() == 1

    # Customer information validation methods
    def validate_customer_info(self):
        """
        Validate customer information fields.
        
        Returns:
            tuple: (is_valid, error_messages)
        """
        errors = []
        
        # Validate primary contact first name
        if self.primary_contact_first_name:
            if len(self.primary_contact_first_name) < 1 or len(self.primary_contact_first_name) > 255:
                errors.append("Primary contact first name must be between 1 and 255 characters")
            if not self._is_valid_name(self.primary_contact_first_name):
                errors.append("Primary contact first name contains invalid characters")
        
        # Validate primary contact last name
        if self.primary_contact_last_name:
            if len(self.primary_contact_last_name) < 1 or len(self.primary_contact_last_name) > 255:
                errors.append("Primary contact last name must be between 1 and 255 characters")
            if not self._is_valid_name(self.primary_contact_last_name):
                errors.append("Primary contact last name contains invalid characters")
        
        # Validate primary contact email
        if self.primary_contact_email:
            if not self._is_valid_email(self.primary_contact_email):
                errors.append("Primary contact email is not a valid email address")
        
        return (len(errors) == 0, errors)
    
    @staticmethod
    def _is_valid_name(name):
        """
        Validate that name contains only letters, spaces, hyphens, and apostrophes.
        
        Args:
            name (str): Name to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        import re
        # Allow letters (including unicode), spaces, hyphens, and apostrophes
        pattern = r"^[\w\s\-']+$"
        return bool(re.match(pattern, name, re.UNICODE))
    
    @staticmethod
    def _is_valid_email(email):
        """
        Validate email format using RFC 5322 standard.
        
        Args:
            email (str): Email to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        import re
        # Simplified RFC 5322 email validation pattern
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    # Provisioning status methods
    def is_provisioning_pending(self):
        """Check if organization provisioning is pending."""
        return self.provisioning_status == self.PROVISIONING_STATUS_PENDING
    
    def is_provisioning_in_progress(self):
        """Check if organization provisioning is in progress."""
        return self.provisioning_status == self.PROVISIONING_STATUS_IN_PROGRESS
    
    def is_provisioning_complete(self):
        """Check if organization provisioning is complete."""
        return self.provisioning_status == self.PROVISIONING_STATUS_COMPLETE
    
    def is_provisioning_failed(self):
        """Check if organization provisioning has failed."""
        return self.provisioning_status == self.PROVISIONING_STATUS_FAILED
    
    def mark_provisioning_started(self):
        """Mark organization provisioning as started."""
        self.provisioning_status = self.PROVISIONING_STATUS_IN_PROGRESS
        self.provisioning_error = None
    
    def mark_provisioning_complete(self):
        """Mark organization provisioning as complete."""
        from datetime import datetime
        self.provisioning_status = self.PROVISIONING_STATUS_COMPLETE
        self.provisioning_error = None
        self.provisioned_at = datetime.utcnow()
    
    def mark_provisioning_failed(self, error_message):
        """
        Mark organization provisioning as failed.
        
        Args:
            error_message (str): Error message describing the failure
        """
        self.provisioning_status = self.PROVISIONING_STATUS_FAILED
        self.provisioning_error = error_message
    
    def reset_provisioning_status(self):
        """Reset provisioning status to pending for retry."""
        self.provisioning_status = self.PROVISIONING_STATUS_PENDING
        self.provisioning_error = None
    
    @property
    def primary_contact_full_name(self):
        """Get full name of primary contact."""
        if self.primary_contact_first_name and self.primary_contact_last_name:
            return "{} {}".format(self.primary_contact_first_name, self.primary_contact_last_name)
        elif self.primary_contact_first_name:
            return self.primary_contact_first_name
        elif self.primary_contact_last_name:
            return self.primary_contact_last_name
        return None
    
    def to_dict_with_customer_info(self):
        """
        Serialize organization to dictionary including customer information.
        
        Returns:
            dict: Organization data with customer information
        """
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'address': self.address,
            'primary_contact_first_name': self.primary_contact_first_name,
            'primary_contact_last_name': self.primary_contact_last_name,
            'primary_contact_email': self.primary_contact_email,
            'primary_contact_user_id': self.primary_contact_user_id,
            'primary_contact_full_name': self.primary_contact_full_name,
            'company_name': self.company_name,
            'address_line1': self.address_line1,
            'address_line2': self.address_line2,
            'city': self.city,
            'state_province': self.state_province,
            'postal_code': self.postal_code,
            'country': self.country,
            'contact_phone': self.contact_phone,
            'organization_email': self.organization_email,
            'provisioning_status': self.provisioning_status,
            'provisioning_error': self.provisioning_error,
            'provisioned_at': self.provisioned_at.isoformat() if self.provisioned_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
