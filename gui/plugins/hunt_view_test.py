#!/usr/bin/env python
# -*- mode: python; encoding: utf-8 -*-

# Copyright 2012 Google Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test the hunt_view interface."""



import traceback

from grr.lib import access_control
from grr.lib import aff4
from grr.lib import flow
from grr.lib import hunt_test
from grr.lib import hunts
from grr.lib import rdfvalue
from grr.lib import test_lib


def CreateHunts():
  """Create some test hunts."""
  test_hunt = hunt_test.HuntTest(methodName="run")
  test_hunt.setUp()
  return test_hunt


class TestHuntView(test_lib.GRRSeleniumTest):
  """Test the Cron view GUI."""

  reason = "Felt like it!"

  @staticmethod
  def SetUp():
    result = TestHuntView(methodName="run")
    result.setUp()
    result.CreateSampleHunt()

    return result

  def setUp(self):
    super(TestHuntView, self).setUp()
    self.hunts = CreateHunts()

  def tearDown(self):
    self.UninstallACLChecks()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw",
                                token=self.token)
    foreman.Set(foreman.Schema.RULES())
    foreman.Close()

    self.hunts.DeleteClients(10)

  def CreateSampleHunt(self, stopped=False):
    self.client_ids = self.hunts.SetupClients(10)

    hunt = hunts.SampleHunt(token=self.token)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])

    if stopped:
      hunt.WriteToDataStore()
    else:
      hunt.Run()

      foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw",
                                  token=self.token)
      for client_id in self.client_ids:
        foreman.AssignTasksToClient(client_id)
      foreman.Close()

    return hunt

  def CreateGenericHuntWithCollection(self):
    self.client_ids = self.hunts.SetupClients(10)

    hunt = hunts.GenericHunt(collect_replies=True, token=self.token)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])

    hunt.collection.Add(rdfvalue.RDFURN("aff4:/sample/1"))
    hunt.collection.Add(rdfvalue.RDFURN(
        "aff4:/C.0000000000000001/fs/os/c/bin/bash"))
    hunt.collection.Add(rdfvalue.RDFURN("aff4:/sample/3"))

    hunt.WriteToDataStore()

    return hunt

  def SetupTestHuntView(self):
    # Create some clients and a hunt to view.
    hunt = self.CreateSampleHunt()
    # Run the hunt.
    client_mock = self.hunts.SampleHuntMock()
    test_lib.TestHuntHelper(client_mock, self.client_ids, False, self.token)
    hunt.LogResult(self.client_ids[2], "Result 1")

    # Log an error just with some random traceback.
    hunt.LogClientError(self.client_ids[1], "Client Error 1",
                        traceback.format_exc())

    hunt_obj = aff4.FACTORY.Open(hunt.session_id, mode="rw",
                                 age=aff4.ALL_TIMES, token=self.token)
    started = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.CLIENTS)
    self.assertEqual(len(set(started)), 10)

  def testHuntView(self):
    """Test that we can see all the hunt data."""
    self.SetupTestHuntView()

    # Open up and click on View Hunts.
    sel = self.selenium
    sel.open("/")
    self.WaitUntil(sel.is_element_present, "client_query")
    self.WaitUntil(sel.is_element_present, "css=a[grrtarget=ManageHunts]")
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Select a Hunt.
    sel.click("css=td:contains('SampleHunt')")

    # Check we can now see the details.
    self.WaitUntil(sel.is_element_present, "css=dl.dl-hunt")
    self.WaitUntil(sel.is_text_present, "Client Count")
    self.WaitUntil(sel.is_text_present, "Hunt URN")

    # Click the Log Tab.
    sel.click("css=a[renderer=HuntLogRenderer]")
    self.WaitUntil(sel.is_element_present, "css=div[id^=HuntLogRenderer_]")
    self.WaitUntil(sel.is_text_present, "Result 1")

    # Click the Error Tab.
    sel.click("css=a[renderer=HuntErrorRenderer]")
    self.WaitUntil(sel.is_element_present, "css=div[id^=HuntErrorRenderer_]")
    self.WaitUntil(sel.is_text_present, "Client Error 1")

    # Click the Rules Tab.
    sel.click("css=a[renderer=HuntRuleRenderer]")
    self.WaitUntil(sel.is_element_present, "css=div[id^=HuntRuleRenderer_]")
    self.WaitUntil(sel.is_text_present, "GRR client")

  def testToolbarStateForStoppedHunt(self):
    self.CreateSampleHunt(stopped=True)
    sel = self.selenium

    sel.open("/")
    self.WaitUntil(sel.is_element_present, "client_query")
    self.WaitUntil(sel.is_element_present, "css=a[grrtarget=ManageHunts]")
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Select a Hunt.
    sel.click("css=td:contains('SampleHunt')")

    # Check we can now see the details.
    self.WaitUntil(sel.is_element_present, "css=dl.dl-hunt")
    self.WaitUntil(sel.is_text_present, "Client Count")
    self.WaitUntil(sel.is_text_present, "Hunt URN")

    self.assertTrue(sel.is_element_present,
                    "css=button[name=RunHunt][disabled!='']")
    self.assertTrue(sel.is_element_present,
                    "css=button[name=PauseHunt][disabled='']")
    self.assertTrue(sel.is_element_present,
                    "css=button[name=ModifyHunt][disabled='']")

  def testToolbarStateForRunningHunt(self):
    self.CreateSampleHunt(stopped=False)
    sel = self.selenium

    sel.open("/")
    self.WaitUntil(sel.is_element_present, "client_query")
    self.WaitUntil(sel.is_element_present, "css=a[grrtarget=ManageHunts]")
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Select a Hunt.
    sel.click("css=td:contains('SampleHunt')")

    # Check we can now see the details.
    self.WaitUntil(sel.is_element_present, "css=dl.dl-hunt")
    self.WaitUntil(sel.is_text_present, "Client Count")
    self.WaitUntil(sel.is_text_present, "Hunt URN")

    self.assertTrue(sel.is_element_present,
                    "css=button[name=RunHunt][disabled='']")
    self.assertTrue(sel.is_element_present,
                    "css=button[name=PauseHunt][disabled!='']")
    self.assertTrue(sel.is_element_present,
                    "css=button[name=ModifyHunt][disabled='']")

  def testRunHuntWithoutACLChecks(self):
    self.CreateSampleHunt(stopped=True)
    sel = self.selenium

    sel.open("/")
    self.WaitUntil(sel.is_element_present, "client_query")
    self.WaitUntil(sel.is_element_present, "css=a[grrtarget=ManageHunts]")
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Select a Hunt.
    sel.click("css=td:contains('SampleHunt')")

    # Check the hunt is not in a running state.
    self.WaitUntil(sel.is_text_present, "stopped")

    # Check we can now see the details.
    self.WaitUntil(sel.is_element_present, "css=dl.dl-hunt")
    self.WaitUntil(sel.is_text_present, "Client Count")
    self.WaitUntil(sel.is_text_present, "Hunt URN")

    # Click on Run button and check that dialog appears.
    sel.click("css=button[name=RunHunt]")
    self.WaitUntil(sel.is_text_present,
                   "Are you sure you want to run this hunt?")

    # Click Cancel and check that dialog disappears.
    sel.click("css=button[name=Cancel]")
    self.WaitUntil(lambda x: not sel.is_element_present(x),
                   "css=.modal-backdrop")

    # Click on Run and wait for dialog again.
    sel.click("css=button[name=RunHunt]")
    self.WaitUntil(sel.is_text_present,
                   "Are you sure you want to run this hunt?")

    # Click on "Proceed" and wait for "Done!" label to appear.
    # Also check that "Proceed" button gets disabled.
    sel.click("css=button[name=Proceed]")
    self.WaitUntil(sel.is_text_present, "Done!")
    self.assertTrue(sel.is_element_present,
                    "css=button[name=Proceed][disabled!='']")

    # Click on "Cancel" and check that dialog disappears.
    sel.click("css=button[name=Cancel]")
    self.WaitUntil(lambda x: not sel.is_element_present(x),
                   "css=.modal-backdrop")

    # TODO(user): make the refresh automatic.
    # Refresh the view.
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Check the hunt is in a running state.
    sel.click("css=td:contains('SampleHunt')")
    self.WaitUntil(sel.is_text_present, "RUNNING")

  def testRunHuntWithACLChecks(self):
    hunt = self.CreateSampleHunt(stopped=True)
    self.InstallACLChecks()

    sel = self.selenium

    sel.open("/")
    self.WaitUntil(sel.is_element_present, "client_query")
    self.WaitUntil(sel.is_element_present, "css=a[grrtarget=ManageHunts]")
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Select a Hunt.
    sel.click("css=td:contains('SampleHunt')")

    # Click on Run button and check that dialog appears.
    sel.click("css=button[name=RunHunt]")
    self.WaitUntil(sel.is_text_present,
                   "Are you sure you want to run this hunt?")

    # Click on "Proceed" and wait for authorization dialog to appear.
    sel.click("css=button[name=Proceed]")

    # This should be rejected now and a form request is made.
    self.WaitUntil(sel.is_text_present,
                   "Create a new approval")
    sel.click("css=#acl_dialog button[name=Close]")
    # Wait for dialog to disappear.
    self.WaitUntil(lambda x: not sel.is_element_present(x),
                   "css=.modal-backdrop")

    # Create the approval and approve it.
    token = access_control.ACLToken(username="test")
    token.supervisor = True
    flow.FACTORY.StartFlow(None, "RequestHuntApprovalFlow",
                           hunt_id=rdfvalue.RDFURN(hunt.session_id).Basename(),
                           reason=self.reason,
                           approver="approver",
                           token=token)

    self.MakeUserAdmin("approver")
    token = access_control.ACLToken(username="approver")
    token.supervisor = True
    flow.FACTORY.StartFlow(None, "GrantHuntApprovalFlow",
                           hunt_urn=hunt.session_id, reason=self.reason,
                           delegate="test",
                           token=token)

    # Click on Run and wait for dialog again.
    sel.click("css=button[name=RunHunt]")
    self.WaitUntil(sel.is_text_present,
                   "Are you sure you want to run this hunt?")

    # Click on "Proceed" and wait for "Done!" label to appear.
    # Also check that "Proceed" button gets disabled.
    sel.click("css=button[name=Proceed]")

    self.WaitUntil(sel.is_text_present, "Done!")
    self.assertTrue(sel.is_element_present,
                    "css=button[name=Proceed][disabled!='']")

    # Click on "Cancel" and check that dialog disappears.
    sel.click("css=button[name=Cancel]")
    self.WaitUntil(lambda x: not sel.is_element_present(x),
                   "css=.modal-backdrop")

    # TODO(user): make the refresh automatic.
    # Refresh the view.
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Check the hunt is in a running state.
    sel.click("css=td:contains('SampleHunt')")
    self.WaitUntil(sel.is_text_present, "RUNNING")

  def testPauseHuntWithoutACLChecks(self):
    self.CreateSampleHunt(stopped=False)
    sel = self.selenium

    sel.open("/")
    self.WaitUntil(sel.is_element_present, "client_query")
    self.WaitUntil(sel.is_element_present, "css=a[grrtarget=ManageHunts]")
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Select a Hunt.
    sel.click("css=td:contains('SampleHunt')")

    # Check the hunt is in a running state.
    self.WaitUntil(sel.is_text_present, "RUNNING")

    # Check we can now see the details.
    self.WaitUntil(sel.is_element_present, "css=dl.dl-hunt")
    self.WaitUntil(sel.is_text_present, "Client Count")
    self.WaitUntil(sel.is_text_present, "Hunt URN")

    # Click on Pause button and check that dialog appears.
    sel.click("css=button[name=PauseHunt]")
    self.WaitUntil(sel.is_text_present,
                   "Are you sure you want to pause this hunt?")

    # Click Cancel and check that dialog disappears.
    sel.click("css=button[name=Cancel]")
    self.WaitUntil(lambda x: not sel.is_element_present(x),
                   "css=.modal-backdrop")

    # Click on Pause and wait for dialog again.
    sel.click("css=button[name=PauseHunt]")
    self.WaitUntil(sel.is_text_present,
                   "Are you sure you want to pause this hunt?")

    # Click on "Proceed" and wait for "Done!" label to appear.
    # Also check that "Proceed" button gets disabled.
    sel.click("css=button[name=Proceed]")
    self.WaitUntil(sel.is_text_present, "Done!")
    self.assertTrue(sel.is_element_present,
                    "css=button[name=Proceed][disabled!='']")

    # Click on "Cancel" and check that dialog disappears.
    sel.click("css=button[name=Cancel]")
    self.WaitUntil(lambda x: not sel.is_element_present(x),
                   "css=.modal-backdrop")

    # TODO(user): make the refresh automatic.
    # Refresh the view.
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Check the hunt is in a running state.
    sel.click("css=td:contains('SampleHunt')")
    self.WaitUntil(sel.is_text_present, "stopped")

  def testPauseHuntWithACLChecks(self):
    hunt = self.CreateSampleHunt(stopped=False)
    self.InstallACLChecks()

    sel = self.selenium

    sel.open("/")
    self.WaitUntil(sel.is_element_present, "client_query")
    self.WaitUntil(sel.is_element_present, "css=a[grrtarget=ManageHunts]")
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Select a Hunt.
    sel.click("css=td:contains('SampleHunt')")

    # Click on Pause button and check that dialog appears.
    sel.click("css=button[name=PauseHunt]")
    self.WaitUntil(sel.is_text_present,
                   "Are you sure you want to pause this hunt?")

    # Click on "Proceed" and wait for authorization dialog to appear.
    sel.click("css=button[name=Proceed]")

    # This should be rejected now and a form request is made.
    self.WaitUntil(sel.is_text_present,
                   "Create a new approval")
    sel.click("css=#acl_dialog button[name=Close]")
    # Wait for dialog to disappear.
    self.WaitUntil(lambda x: not sel.is_element_present(x),
                   "css=.modal-backdrop")

    # Create the approval.
    token = access_control.ACLToken(username="test")
    token.supervisor = True
    flow.FACTORY.StartFlow(None, "RequestHuntApprovalFlow",
                           hunt_id=rdfvalue.RDFURN(hunt.session_id).Basename(),
                           reason=self.reason,
                           approver="approver",
                           token=token)

    self.MakeUserAdmin("approver")
    token = access_control.ACLToken(username="approver")
    token.supervisor = True
    flow.FACTORY.StartFlow(None, "GrantHuntApprovalFlow",
                           hunt_urn=hunt.session_id, reason=self.reason,
                           delegate="test",
                           token=token)

    # Click on Pause and wait for dialog again.
    sel.click("css=button[name=PauseHunt]")
    self.WaitUntil(sel.is_text_present,
                   "Are you sure you want to pause this hunt?")

    # Click on "Proceed" and wait for "Done!" label to appear.
    # Also check that "Proceed" button gets disabled.
    sel.click("css=button[name=Proceed]")
    self.WaitUntil(sel.is_text_present, "Done!")
    self.assertTrue(sel.is_element_present,
                    "css=button[name=Proceed][disabled!='']")

    # Click on "Cancel" and check that dialog disappears.
    sel.click("css=button[name=Cancel]")
    self.WaitUntil(lambda x: not sel.is_element_present(x),
                   "css=.modal-backdrop")

    # TODO(user): make the refresh automatic.
    # Refresh the view.
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Check the hunt is in a running state.
    sel.click("css=td:contains('SampleHunt')")
    self.WaitUntil(sel.is_text_present, "stopped")

  def testModifyHuntWithACLChecks(self):
    self.CreateSampleHunt(stopped=True)
    self.InstallACLChecks()

    sel = self.selenium

    sel.open("/")
    self.WaitUntil(sel.is_element_present, "client_query")
    self.WaitUntil(sel.is_element_present, "css=a[grrtarget=ManageHunts]")
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")

    # Select a Hunt.
    sel.click("css=td:contains('SampleHunt')")

    # Click on Pause button and check that dialog appears.
    sel.click("css=button[name=ModifyHunt]")
    self.WaitUntil(sel.is_text_present,
                   "Modify a hunt")

    sel.type("css=input[name=client_limit]", "4483")
    sel.type("css=input[name=expiry_time]", "5m")

    # Click on "Proceed" and wait for "Done!" label to appear.
    # Also check that "Proceed" button gets disabled.
    sel.click("css=button[name=Proceed]")
    self.WaitUntil(sel.is_text_present, "Done!")
    self.assertTrue(sel.is_element_present,
                    "css=button[name=Proceed][disabled!='']")

    # Click on "Cancel" and check that dialog disappears.
    sel.click("css=button[name=Cancel]")
    self.WaitUntil(lambda x: not sel.is_element_present(x),
                   "css=.modal-backdrop")

    # TODO(user): make the refresh automatic.
    # Refresh the view.
    sel.click("css=a[grrtarget=ManageHunts]")
    self.WaitUntil(sel.is_text_present, "SampleHunt")
    self.WaitUntil(sel.is_text_present, "4483")

  def SetupHuntDetailView(self):
    """Create some clients and a hunt to view."""
    hunt = self.CreateSampleHunt()
    # Run the hunt.
    client_mock = self.hunts.SampleHuntMock()
    test_lib.TestHuntHelper(client_mock, self.client_ids, False, self.token)

    hunt.LogClientError(self.client_ids[1], "Client Error 1",
                        traceback.format_exc())

  def testHuntDetailView(self):
    """Test the detailed client view works."""
    self.SetupHuntDetailView()

    # Open up and click on View Hunts then the first Hunt.
    sel = self.selenium
    sel.open("/")
    self.WaitUntil(sel.is_element_present, "client_query")
    sel.click("css=a[grrtarget=ManageHunts]")

    self.WaitUntil(sel.is_text_present, "SampleHunt")
    sel.click("css=td:contains('SampleHunt')")

    self.WaitUntil(sel.is_element_present,
                   "css=a[renderer=HuntOverviewRenderer]")

    # Click the Overview Tab then the Details Link.
    sel.click("css=a[renderer=HuntOverviewRenderer]")
    self.WaitUntil(sel.is_element_present, "css=div[id^=HuntOverviewRenderer_]")
    self.WaitUntil(sel.is_text_present, "Hunt URN")
    sel.click("css=a[id^=ViewHuntDetails_]")
    self.WaitUntil(sel.is_text_present, "Viewing Hunt aff4:/hunts/")

    self.WaitUntil(sel.is_text_present, "COMPLETED")
    self.WaitUntil(sel.is_text_present, "BAD")

    # Select the first client which should have errors.
    sel.click("css=td:contains('%s')" % self.client_ids[1])
    self.WaitUntil(sel.is_element_present,
                   "css=div[id^=HuntClientOverviewRenderer_]")
    self.WaitUntil(sel.is_text_present, "Last Checkin")

    sel.click("css=a:[renderer=HuntLogRenderer]")
    self.WaitUntil(sel.is_element_present, "css=div[id^=HuntLogRenderer_]")
    self.WaitUntil(sel.is_text_present, "No entries")

    sel.click("css=a:[renderer=HuntErrorRenderer]")
    self.WaitUntil(sel.is_element_present, "css=div[id^=HuntErrorRenderer_]")
    self.WaitUntil(sel.is_text_present, "Client Error 1")

    sel.click("css=a:[renderer=HuntHostInformationRenderer]")
    self.WaitUntil(sel.is_element_present,
                   "css=div[id^=HuntHostInformationRenderer_]")

    self.WaitUntil(sel.is_text_present, "CLIENT_INFO")
    self.WaitUntil(sel.is_text_present, "VFSGRRClient")

  def testHuntResultsView(self):
    self.CreateGenericHuntWithCollection()

    sel = self.selenium
    sel.open("/")
    self.WaitUntil(sel.is_element_present, "client_query")
    sel.click("css=a[grrtarget=ManageHunts]")

    self.WaitUntil(sel.is_text_present, "GenericHunt")
    sel.click("css=td:contains('GenericHunt')")

    self.WaitUntil(sel.is_element_present,
                   "css=a[renderer=HuntResultsRenderer]")
    # Click the Results tab.
    sel.click("css=a[renderer=HuntResultsRenderer]")
    self.WaitUntil(sel.is_element_present, "css=div[id^=HuntResultsRenderer_]")

    self.assertTrue(sel.is_text_present("aff4:/sample/1"))
    self.assertTrue(sel.is_text_present(
        "aff4:/C.0000000000000001/fs/os/c/bin/bash"))
    self.assertTrue(sel.is_text_present("aff4:/sample/3"))

    sel.click("link=aff4:/C.0000000000000001/fs/os/c/bin/bash")
    self.WaitUntil(sel.is_element_present,
                   "css=li.active a:contains('Browse Virtual Filesystem'")

  def testHuntStatsView(self):
    self.SetupTestHuntView()

    sel = self.selenium
    sel.open("/")
    self.WaitUntil(sel.is_element_present, "client_query")
    sel.click("css=a[grrtarget=ManageHunts]")

    self.WaitUntil(sel.is_text_present, "SampleHunt")
    sel.click("css=td:contains('SampleHunt')")

    self.WaitUntil(sel.is_element_present,
                   "css=a[renderer=HuntStatsRenderer]")
    # Click the Stats tab.
    sel.click("css=a[renderer=HuntStatsRenderer]")
    self.WaitUntil(sel.is_element_present, "css=div[id^=HuntStatsRenderer_]")

    self.assertTrue(sel.is_text_present("Total number of clients"))
    self.assertTrue(sel.is_text_present("10"))

    self.assertTrue(sel.is_text_present("User CPU mean"))
    self.assertTrue(sel.is_text_present("5.5"))

    self.assertTrue(sel.is_text_present("User CPU stdev"))
    self.assertTrue(sel.is_text_present("2.9"))

    self.assertTrue(sel.is_text_present("System CPU mean"))
    self.assertTrue(sel.is_text_present("11"))

    self.assertTrue(sel.is_text_present("User CPU stdev"))
    self.assertTrue(sel.is_text_present("5.7"))

    self.assertTrue(sel.is_text_present("Network bytes sent mean"))
    self.assertTrue(sel.is_text_present("16.5"))

    self.assertTrue(sel.is_text_present("Network bytes sent stdev"))
    self.assertTrue(sel.is_text_present("8.6"))
