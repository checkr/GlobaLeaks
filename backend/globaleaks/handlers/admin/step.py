# -*- coding: utf-8
#
#   /admin/steps
#   *****
# Implementation of the code executed on handler /admin/steps
#
from six import text_type

from globaleaks import models
from globaleaks.handlers.admin.field import db_create_field, db_update_field, db_create_trigger, db_reset_option_triggers
from globaleaks.handlers.base import BaseHandler
from globaleaks.handlers.operation import OperationHandler
from globaleaks.handlers.public import serialize_step
from globaleaks.models import fill_localized_keys
from globaleaks.orm import transact
from globaleaks.rest import requests, errors


def db_create_step(session, tid, step_dict, language):
    """
    Create the specified step

    :param session: the session on which perform queries.
    :param language: the language of the specified steps.
    """
    fill_localized_keys(step_dict, models.Step.localized_keys, language)

    step = models.db_forge_obj(session, models.Step, step_dict)

    for trigger in step_dict.get('triggered_by_options', []):
        db_create_trigger(session, tid, trigger['option'], 'step', step.id, trigger.get('sufficient', True))

    for c in step_dict['children']:
        c['tid'] = tid
        c['step_id'] = step.id
        db_create_field(session, tid, c, language)

    return step


@transact
def create_step(session, tid, step, language):
    """
    Transaction that perform db_create_step
    """
    return serialize_step(session, tid, db_create_step(session, tid, step, language), language)


def db_update_step(session, tid, step_id, step_dict, language):
    """
    Update the specified step with the details.

    :param session: the session on which perform queries.
    :param step_id: the step_id of the step to update
    :param step_dict: the step definition dict
    :param language: the language of the step definition dict
    :return: a serialization of the object
    """
    step = models.db_get(session, models.Step, models.Step.id == step_id,
                                               models.Questionnaire.id == models.Step.questionnaire_id,
                                               models.Questionnaire.tid == tid)

    fill_localized_keys(step_dict, models.Step.localized_keys, language)

    step.update(step_dict)

    for child in step_dict['children']:
        db_update_field(session, tid, child['id'], child, language)

    db_reset_option_triggers(session, 'step', step.id)

    for trigger in step_dict.get('triggered_by_options', []):
        db_create_trigger(session, tid, trigger['option'], 'step', step.id, trigger.get('sufficient', True))

    return step


@transact
def update_step(session, tid, step_id, request, language):
    return serialize_step(session, tid, db_update_step(session, tid, step_id, request, language), language)


@transact
def delete_step(session, tid, step_id):
    q_ids = session.query(models.Questionnaire.id).filter(models.Questionnaire.tid == tid)

    session.query(models.Step).filter(models.Step.id == step_id,
                                      models.Step.questionnaire_id.in_(q_ids.subquery())).delete(synchronize_session='fetch')


@transact
def order_elements(session, handler, req_args, *args, **kwargs):
    steps = session.query(models.Step) \
                   .filter(models.Step.questionnaire_id == req_args['questionnaire_id'],
                           models.Questionnaire.id == req_args['questionnaire_id'],
                           models.Questionnaire.tid == handler.request.tid)

    id_dict = {step.id: step for step in steps}
    ids = req_args['ids']

    if len(ids) != len(id_dict) and set(ids) != set(id_dict):
        raise errors.InputValidationError('list does not contain all context ids')

    for i, step_id in enumerate(ids):
        id_dict[step_id].presentation_order = i


class StepCollection(OperationHandler):
    """
    Operation to create a step

    /admin/steps
    """
    check_roles = 'admin'
    cache_resource = True
    invalidate_cache = True

    def post(self):
        """
        Create a new step.

        :return: the serialized step
        :rtype: StepDesc
        :raises InputValidationError: if validation fails.
        """
        request = self.validate_message(self.request.content.read(),
                                        requests.AdminStepDesc)

        return create_step(self.request.tid, request, self.request.language)

    def operation_descriptors(self):
        return {
            'order_elements': (
                order_elements,
                {
                  'questionnaire_id': requests.uuid_regexp,
                  'ids': [text_type],
                }
            )
        }


class StepInstance(BaseHandler):
    """
    Operation to iterate over a specific requested Step

    /admin/step
    """
    check_roles = 'admin'
    invalidate_cache = True

    def put(self, step_id):
        """
        Update attributes of the specified step

        :param step_id:
        :return: the serialized step
        :rtype: StepDesc
        :raises InputValidationError: if validation fails.
        """
        request = self.validate_message(self.request.content.read(),
                                        requests.AdminStepDesc)

        return update_step(self.request.tid, step_id, request, self.request.language)

    def delete(self, step_id):
        """
        Delete the specified step.

        :param step_id:
        :raises InputValidationError: if validation fails.
        """
        return delete_step(self.request.tid, step_id)
