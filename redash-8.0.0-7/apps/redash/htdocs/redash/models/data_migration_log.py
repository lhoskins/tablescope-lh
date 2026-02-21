"""
Data Migration Log Model

This model tracks all data migration operations for shared projects.
It provides an audit trail for troubleshooting and compliance.

Requirements: 24.1, 24.2, 24.3, 24.4, 24.5, 24.6
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from .base import db
from .mixins import TimestampMixin


class DataMigrationLog(TimestampMixin, db.Model):
    """
    Audit log for data migration operations.
    
    Tracks all migration operations when projects are shared or unshared,
    including success, failure, and rollback information.
    """
    __tablename__ = 'data_migration_logs'
    
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    migration_type = Column(String(50), nullable=False)  # 'share' or 'unshare'
    status = Column(String(50), nullable=False)  # 'started', 'completed', 'failed', 'rolled_back'
    initiated_by_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    datasources_migrated = Column(Integer, default=0)
    queries_migrated = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(True), default=db.func.now())
    completed_at = Column(DateTime(True), nullable=True)
    rollback_at = Column(DateTime(True), nullable=True)
    
    # Progress tracking fields (Requirements: 21.1, 21.2, 25.3)
    current_step = Column(String(100), nullable=True)  # e.g., "copying_files", "updating_vdb", "redeploying"
    total_steps = Column(Integer, default=5)  # Total number of steps in migration
    completed_steps = Column(Integer, default=0)  # Number of completed steps
    progress_percentage = Column(Integer, default=0)  # Percentage complete (0-100)
    
    # Relationships
    project = relationship('Project', backref='migration_logs')
    initiated_by = relationship('User', foreign_keys=[initiated_by_id])
    
    # Constraints
    __table_args__ = (
        CheckConstraint(
            "migration_type IN ('share', 'unshare')",
            name='valid_migration_type'
        ),
        CheckConstraint(
            "status IN ('started', 'completed', 'failed', 'rolled_back')",
            name='valid_status'
        ),
    )
    
    @classmethod
    def create_log(cls, project_id, migration_type, user_id):
        """
        Create a new migration log entry.
        
        Requirements: 24.1
        
        Args:
            project_id (int): ID of the project being migrated
            migration_type (str): Type of migration ('share' or 'unshare')
            user_id (int): ID of the user initiating the migration
        
        Returns:
            DataMigrationLog: The created log entry
        """
        log = cls(
            project_id=project_id,
            migration_type=migration_type,
            status='started',
            initiated_by_id=user_id
        )
        db.session.add(log)
        db.session.flush()
        return log
    
    def mark_completed(self, datasources_count, queries_count):
        """
        Mark migration as completed.
        
        Requirements: 24.5
        
        Args:
            datasources_count (int): Number of datasources migrated
            queries_count (int): Number of queries migrated
        """
        self.status = 'completed'
        self.datasources_migrated = datasources_count
        self.queries_migrated = queries_count
        self.completed_at = db.func.now()
    
    def mark_failed(self, error_message):
        """
        Mark migration as failed.
        
        Requirements: 24.6
        
        Args:
            error_message (str): Error message describing the failure
        """
        self.status = 'failed'
        self.error_message = error_message
        self.completed_at = db.func.now()
    
    def mark_rolled_back(self):
        """
        Mark migration as rolled back.
        
        Requirements: 24.6
        """
        self.status = 'rolled_back'
        self.rollback_at = db.func.now()
    
    def update_progress(self, step_name, completed_steps=None):
        """
        Update migration progress.
        
        Requirements: 21.1, 21.2, 25.3
        
        Args:
            step_name (str): Name of the current step
            completed_steps (int, optional): Number of completed steps. If not provided, increments by 1.
        """
        self.current_step = step_name
        
        if completed_steps is not None:
            self.completed_steps = completed_steps
        else:
            self.completed_steps += 1
        
        # Calculate percentage (Requirements: 21.2, 25.3)
        if self.total_steps > 0:
            self.progress_percentage = int((self.completed_steps / float(self.total_steps)) * 100)
        else:
            self.progress_percentage = 0
        
        # Ensure percentage doesn't exceed 100
        if self.progress_percentage > 100:
            self.progress_percentage = 100
    
    def set_total_steps(self, total_steps):
        """
        Set the total number of steps for this migration.
        
        Requirements: 21.2
        
        Args:
            total_steps (int): Total number of steps
        """
        self.total_steps = total_steps
        
        # Recalculate percentage
        if self.total_steps > 0:
            self.progress_percentage = int((self.completed_steps / float(self.total_steps)) * 100)
    
    def to_dict(self):
        """
        Convert the log entry to a dictionary.
        
        Returns:
            dict: Dictionary representation of the log entry
        """
        return {
            'id': self.id,
            'project_id': self.project_id,
            'migration_type': self.migration_type,
            'status': self.status,
            'initiated_by_id': self.initiated_by_id,
            'datasources_migrated': self.datasources_migrated,
            'queries_migrated': self.queries_migrated,
            'error_message': self.error_message,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'rollback_at': self.rollback_at.isoformat() if self.rollback_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            # Progress tracking fields (Requirements: 21.1, 21.2)
            'current_step': self.current_step,
            'total_steps': self.total_steps,
            'completed_steps': self.completed_steps,
            'progress_percentage': self.progress_percentage,
        }
