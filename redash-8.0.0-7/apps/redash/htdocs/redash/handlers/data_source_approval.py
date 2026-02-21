# handlers/data_source_approval.py
import time
from flask import request, jsonify
from flask_restful import abort
from sqlalchemy.exc import SQLAlchemyError
from redash import models
from redash.models import DataSourceApproval, db
from redash.permissions import require_admin, require_permission
from redash.handlers.base import BaseResource, get_object_or_404
import logging

# Configure the logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


class DataSourceApprovalListResource(BaseResource):
    def get(self):
        """Fetch all data source approvals."""
        try:
            approvals = DataSourceApproval.query.all()
            return jsonify([approval.to_dict() for approval in approvals])
        except SQLAlchemyError as e:
            logger.error("Database error: %s", str(e), exc_info=True)
            return {"error": "A database error occurred: {}".format(str(e))}, 500

    def post(self):
        """Create a new data source approval request."""
        try:
            payload = request.get_json(force=True)
            datasource_id = payload.get("datasource_id")
            approval_type = payload.get("approval_type")
            requester_id = payload.get("requester_id")
            project_id = payload.get("project_id", None)
            group_id = payload.get("group_id", None)

            if not datasource_id or not approval_type or not requester_id:
                return {"error": "Missing required fields: datasource_id, approval_type, requester_id"}, 400

            # Fetch requester details
            requester = models.User.query.get(requester_id)
            if not requester:
                return {"error": "Requester not found."}, 404

            # Fetch group and project details
            group = models.Group.query.get(group_id) if group_id else None
            project = models.Project.query.get(project_id) if project_id else None

            new_approval = DataSourceApproval(
                datasource_id=datasource_id,
                approval_type=approval_type,
                status="Pending",
                project_id=project_id if approval_type == "Project" else None,
                group_id=group_id if approval_type == "Group" else None,
                requester_id=requester_id,
                requester_name=requester.name,
                requester_email=requester.email,
                group_name=group.name if group else None,
                project_name=project.name if project else None,
                created_date=time.strftime('%Y-%m-%d %H:%M:%S'),
            )

            db.session.add(new_approval)
            db.session.commit()

            # Create a detailed message
            if approval_type == "Project" and project:
                message = "Successfully requested '{}' to be added to project '{}'.".format(
                    new_approval.datasource_id, project.name
                )
            elif approval_type == "Group" and group:
                message = "Successfully requested '{}' to be added to group '{}'.".format(
                    new_approval.datasource_id, group.name
                )
            else:
                message = "Approval request created successfully."


            logger.info("Approval request created: %s", new_approval.to_dict())
            return {"message": message, "id": new_approval.id}, 201
        except SQLAlchemyError as e:
            logger.error("Database error: %s", str(e), exc_info=True)
            db.session.rollback()
            return {"error": "A database error occurred: {}".format(str(e))}, 500
        except Exception as e:
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return {"error": "An unexpected error occurred: {}".format(str(e))}, 500
    def get(self):
        """Fetch all data source approvals."""
        try:
            approvals = DataSourceApproval.query.all()
            return jsonify([approval.to_dict() for approval in approvals])
        except SQLAlchemyError as e:
            logger.error("Database error: %s", str(e), exc_info=True)
            return {"error": "A database error occurred: {}".format(str(e))}, 500

    def post(self):
        """Create a new data source approval request."""
        try:
            payload = request.get_json(force=True)
            datasource_id = payload.get("datasource_id")
            approval_type = payload.get("approval_type")
            requester_id = payload.get("requester_id")
            project_id = payload.get("project_id", None)
            group_id = payload.get("group_id", None)

            if not datasource_id or not approval_type or not requester_id:
                return {"error": "Missing required fields: datasource_id, approval_type, requester_id"}, 400

            # Fetch requester details
            requester = models.User.query.get(requester_id)
            if not requester:
                return {"error": "Requester not found."}, 404

            # Fetch group and project details
            group = models.Group.query.get(group_id) if group_id else None
            project = models.Project.query.get(project_id) if project_id else None

            new_approval = DataSourceApproval(
                datasource_id=datasource_id,
                approval_type=approval_type,
                status="Pending",
                project_id=project_id if approval_type == "Project" else None,
                group_id=group_id if approval_type == "Group" else None,
                requester_id=requester_id,
                requester_name=requester.name,
                requester_email=requester.email,
                group_name=group.name if group else None,
                project_name=project.name if project else None,
                created_date=time.strftime('%Y-%m-%d %H:%M:%S'),
            )

            db.session.add(new_approval)
            db.session.commit()

            logger.info("Approval request created: %s", new_approval.to_dict())
            return {"message": "Approval request created successfully.", "id": new_approval.id}, 201
        except SQLAlchemyError as e:
            logger.error("Database error: %s", str(e), exc_info=True)
            db.session.rollback()
            return {"error": "A database error occurred: {}".format(str(e))}, 500
        except Exception as e:
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return {"error": "An unexpected error occurred: {}".format(str(e))}, 500


class DataSourceApprovalUpdateResource(BaseResource):
    def post(self, approval_id):
        """Update the status of a data source approval."""
        try:
            payload = request.get_json(force=True)
            new_status = payload.get("status")

            if not new_status:
                return {"error": "Missing 'status' field in request payload"}, 400

            if new_status not in ['Pending', 'Approved', 'Declined']:
                return {"error": "Invalid status value. Must be one of ['Pending', 'Approved', 'Declined']"}, 400

            approval = get_object_or_404(DataSourceApproval.query.filter_by(id=approval_id).first)
            if not approval:
                return {"error": "Approval record not found."}, 404

            approval.status = new_status
            if new_status in ['Approved', 'Declined']:
                approval.approved_date = time.strftime('%Y-%m-%d %H:%M:%S')

                # Populate approver details
                approver = self.current_user
                approval.approver_name = approver.name
                approval.approver_email = approver.email

            if new_status == 'Approved':
                if approval.approval_type == "Project":
                    existing_mapping = models.ProjectDataSource.query.filter_by(
                        project_id=approval.project_id,
                        data_source_id=approval.datasource_id
                    ).first()

                    if not existing_mapping:
                        project_data_source = models.ProjectDataSource(
                            project_id=approval.project_id,
                            data_source_id=approval.datasource_id,
                            owner=approval.data_source_owner_id
                        )
                        db.session.add(project_data_source)
                        logger.info("Data source added to project %s", approval.project_id)

                elif approval.approval_type == "Group":
                    existing_mapping = models.DataSourceGroup.query.filter_by(
                        group_id=approval.group_id,
                        data_source_id=approval.datasource_id
                    ).first()

                    if not existing_mapping:
                        data_source_group = models.DataSourceGroup(
                            group_id=approval.group_id,
                            data_source_id=approval.datasource_id,
                            view_only=False
                        )
                        db.session.add(data_source_group)
                        logger.info("Data source added to group %s", approval.group_id)

            db.session.commit()
            logger.info("Approval updated successfully: %s", approval.to_dict())
            
            # Return the success message
            return {"message": "Approval updated successfully."}, 200
        except SQLAlchemyError as e:
            logger.error("Database error: %s", str(e), exc_info=True)
            db.session.rollback()
            return {"error": "A database error occurred: {}".format(str(e))}, 500
        except Exception as e:
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return {"error": "An unexpected error occurred: {}".format(str(e))}, 500

        """Update the status of a data source approval."""
        try:
            payload = request.get_json(force=True)
            new_status = payload.get("status")

            if not new_status:
                return {"error": "Missing 'status' field in request payload"}, 400

            if new_status not in ['Pending', 'Approved', 'Declined']:
                return {"error": "Invalid status value. Must be one of ['Pending', 'Approved', 'Declined']"}, 400

            approval = get_object_or_404(DataSourceApproval.query.filter_by(id=approval_id).first)
            if not approval:
                return {"error": "Approval record not found."}, 404

            approval.status = new_status
            if new_status in ['Approved', 'Declined']:
                approval.approved_date = time.strftime('%Y-%m-%d %H:%M:%S')

                # Populate approver details
                approver = self.current_user
                approval.approver_name = approver.name
                approval.approver_email = approver.email

            if new_status == 'Approved':
                if approval.approval_type == "Project":
                    # Automatically add the data source to the project
                    existing_mapping = models.ProjectDataSource.query.filter_by(
                        project_id=approval.project_id,
                        data_source_id=approval.datasource_id
                    ).first()

                    if existing_mapping:
                        logger.info("Data source already exists in the project. Skipping addition.")
                    else:
                        project_data_source = models.ProjectDataSource(
                            project_id=approval.project_id,
                            data_source_id=approval.datasource_id,
                            owner=approval.data_source_owner_id
                        )
                        db.session.add(project_data_source)
                        logger.info("Data source added to project %s", approval.project_id)

                elif approval.approval_type == "Group":
                    # Automatically add the data source to the group
                    existing_mapping = models.DataSourceGroup.query.filter_by(
                        group_id=approval.group_id,
                        data_source_id=approval.datasource_id
                    ).first()

                    if existing_mapping:
                        logger.info("Data source already exists in the group. Skipping addition.")
                    else:
                        data_source_group = models.DataSourceGroup(
                            group_id=approval.group_id,
                            data_source_id=approval.datasource_id,
                            view_only=False  # Default to full access
                        )
                        db.session.add(data_source_group)
                        logger.info("Data source added to group %s", approval.group_id)

            db.session.commit()
            logger.info("Approval updated successfully: %s", approval.to_dict())
            return {"message": "Approval updated successfully."}, 200
        except SQLAlchemyError as e:
            logger.error("Database error: %s", str(e), exc_info=True)
            db.session.rollback()
            return {"error": "A database error occurred: {}".format(str(e))}, 500
        except Exception as e:
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            return {"error": "An unexpected error occurred: {}".format(str(e))}, 500
        
class ProjectDataSourceApprovalResource(BaseResource):
    def post(self, project_id):
        """Handle approval for adding a data source to a project."""
        data = request.get_json(force=True)
        if not data:
            return {"error": "Invalid JSON payload"}, 400

        data_source_id = data.get("data_source_id")
        if not data_source_id:
            return {"error": "Data source ID is required"}, 400

        current_user_id = self.current_user.id

        # Fetch the data source
        data_source = models.DataSource.query.get(data_source_id)
        if not data_source:
            return {"error": "Data source not found"}, 404

        # Enforce ownership of the data source
        if data_source.owner != current_user_id:
            return {
                "error": "You can only submit approval requests for data sources you own."
            }, 403

        # Fetch the project
        project = models.Project.query.get(project_id)
        if not project:
            return {"error": "Project not found"}, 404

        # Handle ownership mismatch by creating an approval request
        try:
            if project.owner_id != current_user_id:
                approval_request = models.DataSourceApproval(
                    datasource_id=data_source_id,
                    approval_type="Project",
                    status="Pending",
                    project_owner_id=project.owner_id,
                    project_id=project_id,
                    data_source_owner_id=data_source.owner,
                    comments="Approval required to link data source '{}' to project '{}'.".format(
                        data_source.name, project.name
                    ),
                )
                models.db.session.add(approval_request)
                models.db.session.commit()

                # Log and return approval request creation success
                current_app.logger.info(
                    "Approval request created successfully: %s", approval_request
                )
                return {
                    "action": "request",
                    "message": "Approval request submitted successfully.",
                    "approval_id": approval_request.id,
                }, 200

            # If ownership matches, check if the data source is already linked
            existing_mapping = models.ProjectDataSource.query.filter_by(
                project_id=project_id, data_source_id=data_source_id
            ).first()

            if existing_mapping:
                return {
                    "action": "already_exists",
                    "message": "Data source is already linked to the project.",
                }, 200

            # Directly link the data source to the project
            project_data_source = models.ProjectDataSource(
                project_id=project_id,
                data_source_id=data_source_id,
                owner=current_user_id,
            )
            models.db.session.add(project_data_source)
            models.db.session.commit()

            # Log and return success for direct linking
            current_app.logger.info(
                "Data source linked directly to project: %s", project_data_source
            )
            return {
                "action": "add",
                "message": "Data source successfully linked to the project.",
                "data_source_id": data_source_id,
            }, 201

        except Exception as e:
            # Log errors and return a generic failure response
            current_app.logger.error("Error processing request: %s", str(e))
            return {"error": "An unexpected error occurred while processing the request."}, 500

class GroupDataSourceApprovalResource(BaseResource):
    def post(self, group_id):
        """Handle approval for adding a data source to a group."""
        data = request.get_json(force=True)
        if not data:
            logger.error("Invalid JSON payload")
            return {"error": "Invalid JSON payload"}, 400

        data_source_id = data.get("data_source_id")
        if not data_source_id:
            logger.error("Data source ID is required")
            return {"error": "Data source ID is required"}, 400

        current_user_id = self.current_user.id

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

        logger.debug("Fetched group: %s", group.to_dict())

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

            # Handle ownership mismatch or direct linking
            if data_source.owner == current_user_id:
                if group.owner_id == current_user_id:
                    # User owns both group and data source, add directly
                    logger.info("User owns both group and data source, adding directly.")
                    data_source_group = models.DataSourceGroup(
                        group_id=group_id,
                        data_source_id=data_source_id,
                        view_only=False,  # Default to full access
                    )
                    models.db.session.add(data_source_group)
                    models.db.session.commit()

                    return {
                        "action": "add",
                        "message": "Data source successfully added to the group.",
                        "data_source": data_source.to_dict(),
                    }, 201

                # Ownership mismatch requires approval
                logger.info("Ownership mismatch detected. Creating approval request.")
                approval_request = models.DataSourceApproval(
                    datasource_id=data_source_id,
                    approval_type="Group",
                    status="Pending",
                    group_owner_id=group.owner_id,
                    group_id=group_id,
                    data_source_owner_id=data_source.owner,
                    comments="Approval required to link data source '{}' to group '{}'.".format(
                        data_source.name, group.name
                    ),
                )
                models.db.session.add(approval_request)
                models.db.session.commit()

                logger.debug("Approval request created successfully: %s", approval_request)

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
            models.db.session.rollback()
            return {
                "error": "This data source is already associated with the group. Duplicate entries are not allowed."
            }, 400
        except Exception as e:
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            models.db.session.rollback()
            return {
                "error": "An unexpected error occurred: {}".format(str(e))
            }, 500


