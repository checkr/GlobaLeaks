# -*- encoding: utf-8 -*-
#
# :authors: Arturo Filastò
# :licence: see LICENSE

from twisted.internet.defer import returnValue, inlineCallbacks
from storm.twisted.transact import transact
from storm.locals import Int, Pickle, Date, Unicode, Reference
from storm.exceptions import NotOneError, NoneError

from globaleaks.utils import idops, gltime
from globaleaks.models.base import TXModel, ModelError
from globaleaks.models.tip import InternalTip, Tip, ReceiverTip, File, Folder
from globaleaks.models.admin import Context

from globaleaks.jobs.delivery import Delivery
from globaleaks.jobs.notification import Notification

from globaleaks.scheduler.manager import work_manager
from globaleaks.utils import log

__all__ = ['Submission']

"""
This ORM implementation is called whistleblower, because contain the information mostly useful
for the WBs, other elements used by WBs stay on globaleaks.db.tips.SpecialTip
"""

class SubmissionModelError(ModelError):
    pass

class SubmissionNotFoundError(SubmissionModelError):
    pass

class SubmissionNotOneError(SubmissionModelError):
    pass

class SubmissionNoContextSelectedError(SubmissionModelError):
    pass

class SubmissionContextNotFoundError(SubmissionModelError):
    pass

class SubmissionContextNotOneError(SubmissionModelError):
    pass

class Submission(TXModel):
    """
    This represents a temporary submission. Submissions should be stored here
    until they are transformed into a Tip.
    """
    __storm_table__ = 'submission'

    # XXX we probably want to remove this useless Int ID and only use the
    # random submission_id. This also decreases the kind of derivate data we
    # store on db.
    id = Int(primary=True)
    submission_id = Unicode() # Int()

    fields = Pickle()

    context_selected = Pickle()

    folder_id = Unicode()
    folder = Reference(folder_id, Folder.id)

    creation_time = Date()

    @transact
    def new(self):
        log.debug("[D] %s %s " % (__file__, __name__), "Submission", "new")
        store = self.getStore()

        submission_id = idops.random_submission_id(False)
        creation_time = gltime.utcDateNow()

        submission = Submission()
        submission.submission_id = submission_id
        submission.creation_time = creation_time

        folder = Folder()
        folder.id = idops.random_folder_id()
        store.add(folder)

        submission.folder = folder
        store.add(submission)

        store.commit()
        store.close()

        response = {"submission_id": submission_id,
            "creation_time": gltime.dateToTime(creation_time),
            "folder_id": folder.id
        }
        return response

    @transact
    def add_file(self, submission_id, file_name=None):
        log.debug("[D] %s %s " % (__file__, __name__), "Submission", "add_file", "submission_id", submission_id , "file_name", file_name )
        store = self.getStore()
        submission = store.find(Submission, Submission.submission_id==submission_id).one()

        if not submission:
            store.rollback()
            store.close()
            raise SubmissionNotFoundError

        new_file_id = idops.random_file_id()
        log.debug("Generated this file id %s" % new_file_id)
        new_file = File()
        #new_file.folder = submission.folder
        # XXX setting this to random for the moment
        #new_file.name = new_file_id
        new_file.id = unicode(new_file_id)
        store.add(new_file)

        try:
            store.commit()
        except Exception, e:
            log.exception("Exception: %s %s " % (__file__, __name__), "Submission", "add_file", "submission_id", submission_id, "file_name", file_name )
            store.rollback()
            store.close()
            raise SubmissionModelError(e)

        log.debug("Added file %s to %s" % (submission_id, file_name))
        store.close()
        return new_file_id

    @transact
    def update_fields(self, submission_id, fields):
        log.debug("[D] %s %s " % (__file__, __name__), "Submission", "update_fields", "submission_id", submission_id, "fields", fields )
        store = self.getStore()
        s = store.find(Submission, Submission.submission_id==submission_id).one()

        if not s.fields:
            s.fields = {}

        for k, v in fields.items():
            s.fields[k] = v
        try:
            store.commit()
        except Exception, e:
            log.exception("Exception: %s %s " % (__file__, __name__), "Submission", "update_fields", "submission_id", submission_id, "fields", fields )
            store.rollback()
            store.close()
            raise SubmissionModelError(e)
        store.close()


    @transact
    def select_context(self, submission_id, context):
        log.debug("[D] %s %s " % (__file__, __name__), "Submission", "select-context", "submission_id", submission_id, "context", context )
        store = self.getStore()
        try:
            s = store.find(Submission, Submission.submission_id==submission_id).one()
        except NotOneError, e:
            # XXX these log lines will be removed in the near future
            log.msg("Problem looking up %s" % submission_id)
            log.msg(e)
            store.rollback()
            store.close()
            raise SubmissionNotFoundError

        s.context_selected = context

        try:
            store.commit()
        except Exception, e:
            log.exception("Exception: %s %s " % (__file__, __name__), "Submission", "select_context", "submission_id", submission_id, "context", context )
            store.rollback()
            store.close()
            raise SubmissionModelError(e)

        store.close()

    # TODO def select_receiver


    @transact
    def status(self, submission_id):
        log.debug("[D] %s %s " % (__file__, __name__), "Submission", "status", "submission_id", submission_id )
        store = self.getStore()
        status = None
        try:
            s = store.find(Submission, Submission.submission_id==submission_id).one()

        except NotOneError, e:
            store.rollback()
            store.close()
            raise SubmissionNotOneError

        if not s:
            store.rollback()
            store.close()
            raise SubmissionNotFoundError

        status = {'context_selected': s.context_selected,
                  'fields': s.fields}
                # TODO 'creation_time' and 'expiration_time'

        store.commit()
        store.close()
        return status

    @transact
    def create_tips(self, submission_id, receipt):

        log.debug("[D] %s %s " % (__file__, __name__), "Submission", "create_tips", "submission_id", submission_id, "receipt", receipt )
        log.debug("Creating tips for %s" % submission_id)

        store = self.getStore()
        try:
            submission = store.find(Submission,
                            Submission.submission_id==submission_id).one()
        except NotOneError, e:
            log.msg("Problem creating tips for %s" % submission_id)
            log.msg(e)
            store.rollback()
            store.close()
            # XXX if this happens we probably have to delete one row in the DB
            raise SubmissionModelError("Collision detected! HELP THE WORLD WILL END!")
        except Exception, e:
            log.err("Other random exception")
            log.err(e)
            store.rollback()
            store.close()
            raise SubmissionModelError

        if not submission:
            store.rollback()
            store.close()
            log.msg("Did not find the %s submission" % submission_id)
            raise SubmissionNotFoundError

        if not submission.context_selected:
            store.rollback()
            store.close()
            log.msg("Did not find the context for %s submission" % submission_id)
            raise SubmissionNoContextSelectedError

        try:
            context = store.find(Context,
                    Context.context_id == submission.context_selected).one()
        except NotOneError, e:
            # XXX will this actually ever happen?
            # Investigate!
            store.rollback()
            store.close()
            raise SubmissionContextNotOneError

        if not context:
            store.rollback()
            store.close()
            log.msg("Did not find the context for %s submission" % submission_id)
            raise SubmissionContextNotFoundError

        log.debug("Creating internal tip")
        try:
            internal_tip = InternalTip()
            internal_tip.fields = submission.fields
            internal_tip.context_id = submission.context_selected
            store.add(internal_tip)
        except Exception, e:
            log.err(e)
            store.rollback()
            store.close()
            raise SubmissionModelError

        log.debug("Created internal tip %s" % internal_tip.context_id)

        if submission.folder:
            log.debug("Creating submission folder table %s" % submission.folder_id)
            folder = submission.folder
            folder.internaltip = internal_tip
            try:
                store.add(folder)
                store.commit()
            except Exception, e:
                log.err(e)
                store.rollback()
                store.close()
                raise SubmissionModelError
            log.debug("Submission folder created")

        log.debug("Creating tip for whistleblower")
        whistleblower_tip = Tip()
        whistleblower_tip.internaltip = internal_tip
        whistleblower_tip.address = receipt
        store.add(whistleblower_tip)
        log.debug("Created tip with address %s" % whistleblower_tip.address)

        #receiver_tips = context.create_receiver_tips(internal_tip)
        log.debug("Looking up receivers")
        for receiver in context.receivers:
            log.debug("[D] %s %s " % (__file__, __name__), "Submission", "create_tips", "Creating tip for %s" % receiver.receiver_id)
            receiver_tip = ReceiverTip()
            receiver_tip.internaltip = internal_tip
            receiver_tip.new(receiver.receiver_id)
            store.add(receiver_tip)
            log.debug("Tip created")

            log.debug("Creating delivery jobs")
            delivery_job = Delivery()
            delivery_job.submission_id = submission_id
            delivery_job.receipt_id = receiver_tip.address
            work_manager.add(delivery_job)

            log.debug("Added delivery to %s to the work manager" % receiver.receiver_id)

            notification_job = Notification()
            notification_job.address = receiver.name
            notification_job.receipt_id = receiver_tip.address
            work_manager.add(notification_job)

        log.debug("Deleting the temporary submission %s" % submission.id)

        store.remove(submission)

        try:
            store.commit()
        except Exception, e:
            log.err("Could not create submission")
            log.err(e)
            store.rollback()
        store.close()

