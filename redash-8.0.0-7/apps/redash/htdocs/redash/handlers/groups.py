import time
from flask import request, jsonify
from flask_restful import abort
from redash import models
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql import func
from redash.permissions import require_admin, require_permission
from redash.handlers.base import BaseResource, get_object_or_404
from redash.models.users import Group
from redash.models import DataSource,DataSourceGroup, DataSourceApproval, db, User

import logging

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


class GroupListResource(BaseResource):
    @require_admin
    def post(self):
        """Create a new group with the current user as the owner."""
        data = request.get_json()
        name = data.get('name')

        if not name:
            abort(400, message="The 'name' field is required.")

        # Assign the current user as the owner
        owner_id = self.current_user.id

        # Use default permissions if none are provided
        permissions = data.get('permissions', models.Group.DEFAULT_PERMISSIONS)

        group = models.Group(
            name=name,
            type=data.get('type', models.Group.REGULAR_GROUP),  # Default to 'regular' if not provided
            permissions=permissions,  # Use default permissions if none are provided
            org=self.current_org,  # Assign the current organization
            owner_id=owner_id  # Populate the owner_id field
        )

        models.db.session.add(group)
        models.db.session.commit()

        self.record_event({
            'action': 'create',
            'object_id': group.id,
            'object_type': 'group',
            'owner_id': owner_id,  # Log the owner for audit purposes
            'permissions': permissions,  # Log the permissions assigned
        })

        # Return the created group's details as an object
        return group.to_dict(), 201

    def get(self):
        """Fetch a list of groups the current user can access."""
        if self.current_user.has_permission('admin'):
            groups = models.Group.all(self.current_org)
        else:
            groups = models.Group.query.filter(
                models.Group.id.in_(self.current_user.group_ids)
            ).all()

        self.record_event({
            'action': 'list',
            'object_id': 'groups',
            'object_type': 'group',
        })

        # Ensure the response is an array
        return [group.to_dict() for group in groups], 200


class GroupResource(BaseResource):
    @require_admin
    def post(self, group_id):
        group = models.Group.get_by_id_and_org(group_id, self.current_org)

        if group.type == models.Group.BUILTIN_GROUP:
            abort(400, message="Can't modify built-in groups.")

        group.name = request.json['name']
        models.db.session.commit()

        self.record_event({
            'action': 'edit',
            'object_id': group.id,
            'object_type': 'group'
        })

        return group.to_dict()

    def get(self, group_id):
        if not (self.current_user.has_permission('admin') or int(group_id) in self.current_user.group_ids):
            abort(403)

        group = models.Group.get_by_id_and_org(group_id, self.current_org)

        self.record_event({
            'action': 'view',
            'object_id': group_id,
            'object_type': 'group',
        })

        return group.to_dict()

    @require_admin
    def delete(self, group_id):
        group = models.Group.get_by_id_and_org(group_id, self.current_org)
        if group.type == models.Group.BUILTIN_GROUP:
            abort(400, message="Can't delete built-in groups.")

        members = models.Group.members(group_id)
        for member in members:
            member.group_ids.remove(int(group_id))
            models.db.session.add(member)

        models.db.session.delete(group)
        models.db.session.commit()


class GroupMemberListResource(BaseResource):
    @require_admin
    def post(self, group_id):
        user_id = request.json['user_id']
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        group = models.Group.get_by_id_and_org(group_id, self.current_org)
        user.group_ids.append(group.id)
        models.db.session.commit()

        self.record_event({
            'action': 'add_member',
            'object_id': group.id,
            'object_type': 'group',
            'member_id': user.id
        })
        return user.to_dict()

    @require_permission('list_users')
    def get(self, group_id):
        if not (self.current_user.has_permission('admin') or int(group_id) in self.current_user.group_ids):
            abort(403)

        members = models.Group.members(group_id)
        return [m.to_dict() for m in members]


class GroupMemberResource(BaseResource):
    @require_admin
    def delete(self, group_id, user_id):
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        user.group_ids.remove(int(group_id))
        models.db.session.commit()

        self.record_event({
            'action': 'remove_member',
            'object_id': group_id,
            'object_type': 'group',
            'member_id': user.id
        })


def serialize_data_source_with_group(data_source, data_source_group):
    """
    Helper function to serialize a data source along with group permissions.
    """
    d = data_source.to_dict()
    d['view_only'] = data_source_group.view_only
    return d

class GroupDataSourceListResource(BaseResource):
    @require_admin
    def post(self, group_id):
        """
        Add a data source to a group or create an approval request if needed.
        """
        logger.info("Received request to add data source to group %s", group_id)
        data = request.get_json()
        if not data:
            logger.error("Invalid JSON payload")
            return {"error": "Invalid JSON payload"}, 400

        data_source_id = data.get("data_source_id")
        if not data_source_id:
            logger.error("Data source ID is required")
            return {"error": "Data source ID is required"}, 400

        current_user_id = self.current_user.id
        logger.debug("Current user ID: %s", current_user_id)

        # Fetch the data source
        data_source = models.DataSource.query.get(data_source_id)
        if not data_source:
            logger.error("Data source not found with ID: %s", data_source_id)
            return {"error": "Data source not found"}, 404

        logger.debug("Data source found: %s", data_source.to_dict())

        # Fetch the group
        group = models.Group.get_by_id_and_org(group_id, self.current_org)
        if not group:
            logger.error("Group not found with ID: %s", group_id)
            return {"error": "Group not found"}, 404

        # Fetch requester details
        requester = User.query.get(current_user_id)
        if not requester:
            logger.error("Requester (current user) not found")
            return {"error": "Requester not found"}, 404

        try:
            # Check for existing mapping
            existing_mapping = models.DataSourceGroup.query.filter_by(
                group_id=group_id, data_source_id=data_source_id
            ).first()

            if existing_mapping:
                logger.info("Data source already exists in the group")
                return {
                    "action": "already_exists",
                    "message": "Data source is already added to the group.",
                    "data_source": data_source.to_dict(),
                }, 200

            # Handle ownership mismatch
            if data_source.owner == current_user_id:
                if group.owner_id == current_user_id:
                    # User owns both group and data source, add directly
                    logger.info("User owns both group and data source, adding directly.")
                    data_source_group = models.DataSourceGroup(
                        group_id=group_id,
                        data_source_id=data_source_id,
                        view_only=False,  # Default to full access
                    )
                    db.session.add(data_source_group)
                    db.session.commit()

                    self.record_event({
                        "action": "add_data_source",
                        "object_id": group_id,
                        "object_type": "group",
                        "member_id": data_source.id,
                    })

                    return {
                        "action": "add",
                        "message": "Data source successfully added to the group.",
                        "data_source": data_source.to_dict(),
                    }, 201

                # Ownership mismatch requires approval
                logger.info("Ownership mismatch detected. Creating approval request.")

                # Fetch approver details
                approver = User.query.get(group.owner_id)
                approver_name = approver.name if approver else "N/A"
                approver_email = approver.email if approver else "N/A"

                approval_request = models.DataSourceApproval(
                    datasource_id=data_source_id,
                    approval_type="Group",
                    status="Pending",
                    group_id=group_id,
                    group_name=group.name,  # Add group name
                    requester_id=current_user_id,
                    requester_name=requester.name,
                    requester_email=requester.email,
                    group_owner_id=group.owner_id,
                    approver_name=approver_name,
                    approver_email=approver_email,
                    data_source_owner_id=data_source.owner,
                    comments="Approval required to link data source '{}' to group '{}'.".format(
                        data_source.name, group.name
                    ),
                )
                db.session.add(approval_request)
                db.session.commit()

                return {
                    "action": "request",
                    "message": "Approval request submitted successfully.",
                    "approval_id": approval_request.id,
                }, 200

            # User does not own the data source
            logger.error("User does not own the data source.")
            return {
                "error": "You can only submit approval requests for data sources you own."
            }, 403

        except IntegrityError as e:
            logger.error("IntegrityError: %s", str(e), exc_info=True)
            db.session.rollback()
            return {
                "error": "This data source is already associated with the group. Duplicate entries are not allowed."
            }, 400
        except SQLAlchemyError as e:
            logger.error("SQLAlchemyError: %s", str(e), exc_info=True)
            db.session.rollback()
            return {
                "error": "An unexpected database error occurred: {}".format(str(e))
            }, 500
        except Exception as e:
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            db.session.rollback()
            return {
                "error": "An unexpected error occurred: {}".format(str(e))
            }, 500
    def get(self, group_id):
        """
        Fetch all data sources associated with a group, restricted to those owned by the current user.
        """
        logger.info("Fetching data sources for group %s", group_id)
        try:
            group = Group.get_by_id_and_org(group_id, self.current_org)
            if not group:
                logger.error("Group not found with ID: %s", group_id)
                return {"error": "Group not found"}, 404

            # Fetch data sources associated with the group and owned by the current user
            data_sources = DataSource.query.join(DataSourceGroup).filter(
                DataSourceGroup.group_id == group_id,
                DataSource.owner == self.current_user.id
            ).all()

            logger.debug("Filtered data sources: %s", [ds.to_dict() for ds in data_sources])

            self.record_event({
                "action": "list",
                "object_id": group_id,
                "object_type": "group",
            })

            return [ds.to_dict() for ds in data_sources], 200
        except Exception as e:
            logger.error("Error fetching data sources for group %s: %s", group_id, str(e), exc_info=True)
            return {"error": "Failed to fetch data sources: {}".format(str(e))}, 500

class GroupDataSourceResource(BaseResource):
    @require_admin
    def post(self, group_id, data_source_id):
        data_source = models.DataSource.get_by_id_and_org(data_source_id, self.current_org)
        group = models.Group.get_by_id_and_org(group_id, self.current_org)
        view_only = request.json['view_only']

        data_source_group = data_source.update_group_permission(group, view_only)
        models.db.session.commit()

        self.record_event({
            'action': 'change_data_source_permission',
            'object_id': group_id,
            'object_type': 'group',
            'member_id': data_source.id,
            'view_only': view_only
        })

        return serialize_data_source_with_group(data_source, data_source_group)

    @require_admin
    def delete(self, group_id, data_source_id):
        data_source = models.DataSource.get_by_id_and_org(data_source_id, self.current_org)
        group = models.Group.get_by_id_and_org(group_id, self.current_org)

        data_source.remove_group(group)
        models.db.session.commit()

        self.record_event({
            'action': 'remove_data_source',
            'object_id': group_id,
            'object_type': 'group',
            'member_id': data_source.id
        })

class SharedGroupListResource(BaseResource):
    def get(self):
        """
        Return groups where the current user is either:
        1. The owner of the group, or
        2. A member of the group (group.id is in the user's groups array).
        Include all data sources and members associated with these groups.
        """
        current_user_id = self.current_user.id

        try:
            # Use a subquery with unnest to handle the array comparison
            user_groups_subquery = db.session.query(
                func.unnest(User.group_ids).label('group_id')
            ).filter(User.id == current_user_id).subquery()

            # Fetch groups where the user is either the owner or a member
            groups = Group.query.filter(
                (Group.owner_id == current_user_id) |
                (Group.id.in_(db.session.query(user_groups_subquery.c.group_id)))
            ).all()

            result = []
            for group in groups:
                group_data = group.to_dict()

                # Fetch associated data sources for the group
                group_data['data_sources'] = [
                    serialize_data_source_with_group(ds.data_source, ds)
                    for ds in group.data_sources
                ]

                # Call the Group.members method and execute the query
                group_members = Group.members(group.id).all()
                group_data['members'] = [member.to_dict() for member in group_members]

                result.append(group_data)

            self.record_event({
                'action': 'list_shared_groups_with_data_sources_and_members',
                'object_id': current_user_id,
                'object_type': 'user',
            })

            return jsonify(result), 200
        except Exception as e:
            logger.error("Error fetching shared groups for user %s: %s", current_user_id, str(e), exc_info=True)
            return {"error": "Failed to fetch shared groups: {}".format(str(e))}, 500
