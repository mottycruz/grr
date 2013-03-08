#!/usr/bin/env python
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


"""Tests for the hunt."""



import math
import time


from grr.client import conf
import logging

# pylint: disable=unused-import,g-bad-import-order
from grr.lib import server_plugins
# pylint: enable=unused-import,g-bad-import-order

from grr.lib import aff4
from grr.lib import flow

# These imports populate the GRRHunt registry.
from grr.lib import hunts
from grr.lib import rdfvalue
from grr.lib import test_lib


class BrokenSampleHunt(hunts.SampleHunt):

  @flow.StateHandler()
  def StoreResults(self, responses):
    """Stores the responses."""
    client_id = responses.request.client_id

    if not responses.success:
      logging.info("Client %s has no file /tmp/evil.txt", client_id)
      # Raise on one of the code paths.
      raise RuntimeError("Error")
    else:
      logging.info("Client %s has a file /tmp/evil.txt", client_id)
      self.MarkClientBad(client_id)

    self.MarkClientDone(client_id)


class HuntTest(test_lib.FlowTestsBaseclass):
  """Tests the Hunt."""

  def testRuleAdding(self):

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    rules = foreman.Get(foreman.Schema.RULES)
    # Make sure there are no rules yet.
    self.assertEqual(len(rules), 0)

    hunt = hunts.SampleHunt(token=self.token)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="HUNT")

    int_rule = rdfvalue.ForemanAttributeInteger(
        attribute_name="Clock",
        operator=rdfvalue.ForemanAttributeInteger.Enum("GREATER_THAN"),
        value=1336650631137737)

    hunt.AddRule([int_rule, regex_rule])
    # Push the rules to the foreman.
    hunt.Run()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    rules = foreman.Get(foreman.Schema.RULES)

    # Make sure they were written correctly.
    self.assertEqual(len(rules), 1)
    rule = rules[0]

    self.assertEqual(len(rule.regex_rules), 1)
    self.assertEqual(rule.regex_rules[0].attribute_name, "GRR client")
    self.assertEqual(rule.regex_rules[0].attribute_regex, "HUNT")

    self.assertEqual(len(rule.integer_rules), 1)
    self.assertEqual(rule.integer_rules[0].attribute_name, "Clock")
    self.assertEqual(rule.integer_rules[0].operator,
                     rdfvalue.ForemanAttributeInteger.Enum("GREATER_THAN"))
    self.assertEqual(rule.integer_rules[0].value, 1336650631137737)

    self.assertEqual(len(rule.actions), 1)
    self.assertEqual(rule.actions[0].hunt_name, "SampleHunt")

    # Running a second time should not change the rules any more.
    hunt.Run()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    rules = foreman.Get(foreman.Schema.RULES)

    # Still just one rule.
    self.assertEqual(len(rules), 1)

  def AddForemanRules(self, to_add):
    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    rules = foreman.Get(foreman.Schema.RULES) or foreman.Schema.RULES()
    for rule in to_add:
      rules.Append(rule)
    foreman.Set(foreman.Schema.RULES, rules)
    foreman.Close()

  def testStopping(self):
    """Tests if we can stop a hunt."""

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    rules = foreman.Get(foreman.Schema.RULES)
    # Make sure there are no rules yet.
    self.assertEqual(len(rules), 0)
    now = int(time.time() * 1e6)
    expires = now + 3600
    # Add some rules.
    rules = [rdfvalue.ForemanRule(created=now, expires=expires,
                                  description="Test rule1"),
             rdfvalue.ForemanRule(created=now, expires=expires,
                                  description="Test rule2")]
    self.AddForemanRules(rules)

    hunt = hunts.SampleHunt(token=self.token)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="HUNT")
    int_rule = rdfvalue.ForemanAttributeInteger(
        attribute_name="Clock",
        operator=rdfvalue.ForemanAttributeInteger.Enum("GREATER_THAN"),
        value=1336650631137737)
    # Fire on either of the rules.
    hunt.AddRule([int_rule])
    hunt.AddRule([regex_rule])
    # Push the rules to the foreman.
    hunt.Run()

    # Add some more rules.
    rules = [rdfvalue.ForemanRule(created=now, expires=expires,
                                  description="Test rule3"),
             rdfvalue.ForemanRule(created=now, expires=expires,
                                  description="Test rule4")]
    self.AddForemanRules(rules)

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    rules = foreman.Get(foreman.Schema.RULES)
    self.assertEqual(len(rules), 6)
    self.assertNotEqual(hunt.OutstandingRequests(), 0)

    # Now we stop the hunt.
    hunt.Stop()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    rules = foreman.Get(foreman.Schema.RULES)
    # The rule for this hunt should be deleted but the rest should be there.
    self.assertEqual(len(rules), 4)
    # And the hunt should report no outstanding requests any more.
    self.assertEqual(hunt.OutstandingRequests(), 0)

  def testInvalidRules(self):
    """Tests the behavior when a wrong attribute name is passed in a rule."""

    hunt = hunts.SampleHunt(token=self.token)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="no such attribute",
        attribute_regex="HUNT")
    self.assertRaises(RuntimeError, hunt.AddRule, [regex_rule])

  def Callback(self, hunt_id, client_id, client_limit):
    self.called.append((hunt_id, client_id, client_limit))

  def testCallback(self, client_limit=None):
    """Checks that the foreman uses the callback specified in the action."""

    hunt = hunts.SampleHunt(client_limit=client_limit, token=self.token)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])
    hunt.Run()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)

    # Create a client that matches our regex.
    client = aff4.FACTORY.Open(self.client_id, mode="rw", token=self.token)
    info = client.Schema.CLIENT_INFO()
    info.client_name = "GRR Monitor"
    client.Set(client.Schema.CLIENT_INFO, info)
    client.Close()

    old_start_client = hunts.SampleHunt.StartClient
    try:
      hunts.SampleHunt.StartClient = self.Callback
      self.called = []

      foreman.AssignTasksToClient(client.client_id)

      self.assertEqual(len(self.called), 1)
      self.assertEqual(self.called[0][1], client.client_id)

      # Clean up.
      foreman.Set(foreman.Schema.RULES())
      foreman.Close()
    finally:
      hunts.SampleHunt.StartClient = staticmethod(old_start_client)

  def testStartClient(self):
    hunt = hunts.SampleHunt(token=self.token)
    hunt.Run()

    client = aff4.FACTORY.Open("aff4:/%s" % self.client_id, token=self.token,
                               age=aff4.ALL_TIMES)

    flows = client.GetValuesForAttribute(client.Schema.FLOW)

    self.assertEqual(flows, [])

    hunts.GRRHunt.StartClient(hunt.session_id, self.client_id)

    test_lib.TestHuntHelper(None, [self.client_id], False, self.token)

    client = aff4.FACTORY.Open("aff4:/%s" % self.client_id, token=self.token,
                               age=aff4.ALL_TIMES)

    flows = client.GetValuesForAttribute(client.Schema.FLOW)

    # One flow should have been started.
    self.assertEqual(len(flows), 1)

  def testCallbackWithLimit(self):

    self.assertRaises(RuntimeError, self.testCallback, 2000)

    self.testCallback(100)

  class SampleHuntMock(object):

    def __init__(self):
      self.responses = 0
      self.data = "Hello World!"

    def StatFile(self, args):
      return self._StatFile(args)

    def _StatFile(self, args):
      req = rdfvalue.ListDirRequest(args)

      response = rdfvalue.StatEntry(
          pathspec=req.pathspec,
          st_mode=33184,
          st_ino=1063090,
          st_dev=64512L,
          st_nlink=1,
          st_uid=139592,
          st_gid=5000,
          st_size=len(self.data),
          st_atime=1336469177,
          st_mtime=1336129892,
          st_ctime=1336129892)

      self.responses += 1

      # Create status message to report sample resource usage
      status = rdfvalue.GrrStatus(status=rdfvalue.GrrStatus.Enum("OK"))
      status.cpu_time_used.user_cpu_time = self.responses
      status.cpu_time_used.system_cpu_time = self.responses * 2
      status.network_bytes_sent = self.responses * 3

      # Every second client does not have this file.
      if self.responses % 2:
        return [status]

      return [response, status]

    def TransferBuffer(self, args):

      response = rdfvalue.BufferReference(args)
      response.data = self.data
      response.length = len(self.data)
      return [response]

  class RaisingSampleHuntMock(SampleHuntMock):

    def StatFile(self, args):
      if self.responses == 3:
        self.responses += 1
        raise RuntimeError("This client fails.")

      return self._StatFile(args)

  def testProcessing(self):
    """This tests running the hunt on some clients."""

    # Set up 10 clients.
    client_ids = self.SetupClients(10)

    hunt = hunts.SampleHunt(token=self.token)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])
    hunt.Run()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in client_ids:
      foreman.AssignTasksToClient(client_id)

    # Run the hunt.
    client_mock = self.SampleHuntMock()
    test_lib.TestHuntHelper(client_mock, client_ids, False, self.token)

    hunt_obj = aff4.FACTORY.Open(
        hunt.session_id, mode="r", age=aff4.ALL_TIMES, required_type="VFSHunt",
        token=self.token)

    started = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.CLIENTS)
    finished = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.FINISHED)
    badness = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.BADNESS)

    self.assertEqual(len(set(started)), 10)
    self.assertEqual(len(set(finished)), 10)
    self.assertEqual(len(set(badness)), 5)

    # Clean up.
    foreman.Set(foreman.Schema.RULES())
    foreman.Close()

    self.DeleteClients(10)

  def testHangingClients(self):
    """This tests if the hunt completes when some clients hang or raise."""
    # Set up 10 clients.
    client_ids = self.SetupClients(10)

    hunt = hunts.SampleHunt(token=self.token)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])
    hunt.Run()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in client_ids:
      foreman.AssignTasksToClient(client_id)

    client_mock = self.SampleHuntMock()
    # Just pass 8 clients to run, the other two went offline.
    test_lib.TestHuntHelper(client_mock, client_ids[1:9], False, self.token)

    hunt_obj = aff4.FACTORY.Open(hunt.session_id, mode="rw",
                                 age=aff4.ALL_TIMES, token=self.token)

    started = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.CLIENTS)
    finished = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.FINISHED)
    badness = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.BADNESS)

    # We started the hunt on 10 clients.
    self.assertEqual(len(set(started)), 10)
    # But only 8 should have finished.
    self.assertEqual(len(set(finished)), 8)
    # The client that raised should not show up here.
    self.assertEqual(len(set(badness)), 4)

    # Clean up.
    foreman.Set(foreman.Schema.RULES())
    foreman.Close()

    self.DeleteClients(10)

  def testPausingAndRestartingDoesNotStartHuntTwiceOnTheSameClient(self):
    """This tests if the hunt completes when some clients hang or raise."""
    client_ids = self.SetupClients(10)

    hunt = hunts.SampleHunt(token=self.token)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])
    hunt.Run()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in client_ids:
      num_tasks = foreman.AssignTasksToClient(client_id)
      self.assertEqual(num_tasks, 1)

    client_mock = self.SampleHuntMock()
    test_lib.TestHuntHelper(client_mock, client_ids, False, self.token)

    # Pausing and running hunt: this leads to the fresh rules being written
    # to Foreman.RULES.
    hunt.Pause()
    hunt.Run()
    # Recreating the foreman so that it updates list of rules.
    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in client_ids:
      num_tasks = foreman.AssignTasksToClient(client_id)
      # No tasks should be assigned as this hunt ran of all the clients before.
      self.assertEqual(num_tasks, 0)

    foreman.Set(foreman.Schema.RULES())
    foreman.Close()

    self.DeleteClients(10)

  def testClientLimit(self):
    """This tests that we can limit hunts to a number of clients."""

    # Set up 10 clients.
    client_ids = self.SetupClients(10)

    hunt = hunts.SampleHunt(token=self.token, client_limit=5)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])
    hunt.Run()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in client_ids:
      foreman.AssignTasksToClient(client_id)

    # Run the hunt.
    client_mock = self.SampleHuntMock()
    test_lib.TestHuntHelper(client_mock, client_ids, False, self.token)

    hunt_obj = aff4.FACTORY.Open(hunt.session_id, mode="rw",
                                 age=aff4.ALL_TIMES, token=self.token)

    started = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.CLIENTS)
    finished = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.FINISHED)
    badness = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.BADNESS)

    # We limited here to 5 clients.
    self.assertEqual(len(set(started)), 5)
    self.assertEqual(len(set(finished)), 5)
    self.assertEqual(len(set(badness)), 2)

    # Clean up.
    foreman.Set(foreman.Schema.RULES())
    foreman.Close()

    self.DeleteClients(10)

  def testBrokenHunt(self):
    """This tests the behavior when a hunt raises an exception."""

    # Set up 10 clients.
    client_ids = self.SetupClients(10)

    hunt = BrokenSampleHunt(token=self.token)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])
    hunt.Run()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in client_ids:
      foreman.AssignTasksToClient(client_id)

    # Run the hunt.
    client_mock = self.SampleHuntMock()
    test_lib.TestHuntHelper(client_mock, client_ids, False, self.token)

    hunt_obj = aff4.FACTORY.Open(hunt.session_id, mode="rw",
                                 age=aff4.ALL_TIMES, token=self.token)

    started = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.CLIENTS)
    finished = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.FINISHED)
    badness = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.BADNESS)
    errors = hunt_obj.GetValuesForAttribute(hunt_obj.Schema.ERRORS)

    self.assertEqual(len(set(started)), 10)
    # There should be errors for the five clients where the hunt raised.
    self.assertEqual(len(set(errors)), 5)
    # All of the clients that have the file should still finish eventually.
    self.assertEqual(len(set(finished)), 5)
    self.assertEqual(len(set(badness)), 5)

    # Clean up.
    foreman.Set(foreman.Schema.RULES())
    foreman.Close()

    self.DeleteClients(10)

  def testHuntNotifications(self):
    """This tests the Hunt notification event."""

    received_events = []

    class Listener1(flow.EventListener):  # pylint:disable=W0612
      well_known_session_id = "aff4:/flows/W:TestHuntDone"
      EVENTS = ["TestHuntDone"]

      @flow.EventHandler(auth_required=True)
      def ProcessMessage(self, message=None, event=None):
        _ = event
        # Store the results for later inspection.
        received_events.append(message)

    # Set up 10 clients.
    client_ids = self.SetupClients(10)

    hunt = BrokenSampleHunt(notification_event="TestHuntDone",
                            token=self.token)
    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])
    hunt.Run()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in client_ids:
      foreman.AssignTasksToClient(client_id)

    # Run the hunt.
    client_mock = self.SampleHuntMock()
    test_lib.TestHuntHelper(client_mock, client_ids, check_flow_errors=False,
                            token=self.token)

    self.assertEqual(len(received_events), 5)

    # Clean up.
    foreman.Set(foreman.Schema.RULES())
    foreman.Close()

    self.DeleteClients(10)

  def CheckTuple(self, tuple1, tuple2):
    (a, b) = tuple1
    (c, d) = tuple2

    self.assertAlmostEqual(a, c)
    self.assertAlmostEqual(b, d)

  def testResourceUsage(self):

    hunt_urn = aff4.ROOT_URN.Add("hunts").Add("SampleHunt")
    hunt_obj = aff4.FACTORY.Create(hunt_urn, "VFSHunt", token=self.token)

    usages = [("client1", "flow1", 0.5, 0.5),
              ("client1", "flow2", 0.1, 0.5),
              ("client1", "flow3", 0.2, 0.5),
              ("client2", "flow4", 0.6, 0.5),
              ("client2", "flow5", 0.7, 0.5),
              ("client2", "flow6", 0.6, 0.5),
              ("client3", "flow7", 0.1, 0.5),
              ("client3", "flow8", 0.1, 0.5),
             ]

    # Add some client stats.
    for (client_id, session_id, user, sys) in usages:
      resource = hunt_obj.Schema.RESOURCES()
      resource.client_id = client_id
      resource.session_id = session_id
      resource.cpu_usage.user_cpu_time = user
      resource.cpu_usage.system_cpu_time = sys
      hunt_obj.AddAttribute(resource)

    hunt_obj.Close()

    hunt_obj = aff4.FACTORY.Open(hunt_urn, age=aff4.ALL_TIMES, token=self.token)

    # Just for one client.
    res = hunt_obj.GetResourceUsage(client_id="client1", group_by_client=False)

    self.assertEqual(sorted(res.keys()), ["client1"])
    self.assertEqual(sorted(res["client1"].keys()),
                     ["flow1", "flow2", "flow3"])
    self.CheckTuple(res["client1"]["flow1"], (0.5, 0.5))
    self.CheckTuple(res["client1"]["flow2"], (0.1, 0.5))

    # Group by client_id.
    res = hunt_obj.GetResourceUsage(client_id="client1", group_by_client=True)

    self.assertEqual(sorted(res.keys()), ["client1"])
    self.CheckTuple(res["client1"], (0.8, 1.5))

    # Now for all clients.
    res = hunt_obj.GetResourceUsage(group_by_client=False)

    self.assertEqual(sorted(res.keys()), ["client1", "client2", "client3"])
    self.assertEqual(sorted(res["client1"].keys()),
                     ["flow1", "flow2", "flow3"])
    self.CheckTuple(res["client1"]["flow1"], (0.5, 0.5))
    self.CheckTuple(res["client1"]["flow2"], (0.1, 0.5))

    self.assertEqual(sorted(res["client2"].keys()),
                     ["flow4", "flow5", "flow6"])
    self.CheckTuple(res["client2"]["flow4"], (0.6, 0.5))
    self.CheckTuple(res["client2"]["flow5"], (0.7, 0.5))

    # Group by client_id.
    res = hunt_obj.GetResourceUsage(group_by_client=True)

    self.assertEqual(sorted(res.keys()), ["client1", "client2", "client3"])
    self.CheckTuple(res["client1"], (0.8, 1.5))
    self.CheckTuple(res["client2"], (1.9, 1.5))
    self.CheckTuple(res["client3"], (0.2, 1.0))

  def testResourceUsageStats(self):
    client_ids = self.SetupClients(10)

    hunt = hunts.SampleHunt(token=self.token)
    hunt_urn = hunt.session_id

    regex_rule = rdfvalue.ForemanAttributeRegex(
        attribute_name="GRR client",
        attribute_regex="GRR")
    hunt.AddRule([regex_rule])
    hunt.Run()

    foreman = aff4.FACTORY.Open("aff4:/foreman", mode="rw", token=self.token)
    for client_id in client_ids:
      foreman.AssignTasksToClient(client_id)

    client_mock = self.SampleHuntMock()
    test_lib.TestHuntHelper(client_mock, client_ids, False, self.token)

    # Just in case - unserializing hunt object stored in AFF4 hunt object
    aff4_hunt = aff4.FACTORY.Open(hunt_urn, required_type="VFSHunt",
                                  token=self.token)
    hunt = aff4_hunt.GetFlowObj()

    self.assertEqual(hunt.usage_stats.user_cpu_stats.num, 10)
    self.assertTrue(math.fabs(hunt.usage_stats.user_cpu_stats.mean -
                              5.5) < 1e-7)
    self.assertTrue(math.fabs(hunt.usage_stats.user_cpu_stats.std -
                              2.872281323) < 1e-7)

    self.assertEqual(hunt.usage_stats.system_cpu_stats.num, 10)
    self.assertTrue(math.fabs(hunt.usage_stats.system_cpu_stats.mean -
                              11) < 1e-7)
    self.assertTrue(math.fabs(hunt.usage_stats.system_cpu_stats.std -
                              5.7445626465) < 1e-7)

    self.assertEqual(hunt.usage_stats.network_bytes_sent_stats.num, 10)
    self.assertTrue(math.fabs(hunt.usage_stats.network_bytes_sent_stats.mean -
                              16.5) < 1e-7)
    self.assertTrue(math.fabs(hunt.usage_stats.network_bytes_sent_stats.std -
                              8.616843969) < 1e-7)

    # NOTE: Not checking histograms here. RunningStatsTest tests that mean,
    # standard deviation and histograms are calculated correctly. Therefore
    # if mean/stdev values are correct histograms should be ok as well.

    self.assertEqual(len(hunt.usage_stats.worst_performers), 10)

    prev = hunt.usage_stats.worst_performers[0]
    for p in hunt.usage_stats.worst_performers[1:]:
      self.assertTrue(prev.cpu_usage.user_cpu_time +
                      prev.cpu_usage.system_cpu_time >
                      p.cpu_usage.user_cpu_time +
                      p.cpu_usage.system_cpu_time)
      prev = p


class FlowTestLoader(test_lib.GRRTestLoader):
  base_class = test_lib.FlowTestsBaseclass


def main(argv):
  # Run the full test suite
  test_lib.GrrTestProgram(argv=argv, testLoader=FlowTestLoader())

if __name__ == "__main__":
  conf.StartMain(main)
