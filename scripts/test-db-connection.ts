/**
 * Test Supabase Database Connection
 * Run with: npx tsx scripts/test-db-connection.ts
 */

import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

async function testConnection() {
  console.log("🔍 Testing Supabase connection...\n");

  if (!supabaseUrl || !supabaseKey) {
    console.error("❌ Missing environment variables!");
    console.error("   NEXT_PUBLIC_SUPABASE_URL:", supabaseUrl ? "✅" : "❌");
    console.error("   NEXT_PUBLIC_SUPABASE_ANON_KEY:", supabaseKey ? "✅" : "❌");
    process.exit(1);
  }

  const supabase = createClient(supabaseUrl, supabaseKey);

  // Test 1: Check people table
  console.log("1️⃣ Testing 'people' table...");
  const { data: people, error: peopleError } = await supabase
    .from("people")
    .select("*")
    .limit(1);

  if (peopleError) {
    console.error("   ❌ Error:", peopleError.message);
  } else {
    console.log("   ✅ People table accessible");
    console.log("   📊 Sample count:", people?.length || 0);
  }

  // Test 2: Check memories table
  console.log("\n2️⃣ Testing 'memories' table...");
  const { data: memories, error: memoriesError } = await supabase
    .from("memories")
    .select("*")
    .limit(1);

  if (memoriesError) {
    console.error("   ❌ Error:", memoriesError.message);
  } else {
    console.log("   ✅ Memories table accessible");
    console.log("   📊 Sample count:", memories?.length || 0);
  }

  // Test 3: Check follow_ups table
  console.log("\n3️⃣ Testing 'follow_ups' table...");
  const { data: followUps, error: followUpsError } = await supabase
    .from("follow_ups")
    .select("*")
    .limit(1);

  if (followUpsError) {
    console.error("   ❌ Error:", followUpsError.message);
  } else {
    console.log("   ✅ Follow-ups table accessible");
    console.log("   📊 Sample count:", followUps?.length || 0);
  }

  // Test 4: Check events table
  console.log("\n4️⃣ Testing 'events' table...");
  const { data: events, error: eventsError } = await supabase
    .from("events")
    .select("*")
    .limit(1);

  if (eventsError) {
    console.error("   ❌ Error:", eventsError.message);
  } else {
    console.log("   ✅ Events table accessible");
    console.log("   📊 Sample count:", events?.length || 0);
  }

  // Test 5: Check memory_people junction table
  console.log("\n5️⃣ Testing 'memory_people' table...");
  const { data: memoryPeople, error: memoryPeopleError } = await supabase
    .from("memory_people")
    .select("*")
    .limit(1);

  if (memoryPeopleError) {
    console.error("   ❌ Error:", memoryPeopleError.message);
  } else {
    console.log("   ✅ Memory-People table accessible");
    console.log("   📊 Sample count:", memoryPeople?.length || 0);
  }

  // Test 6: Check people_business_profiles table
  console.log("\n6️⃣ Testing 'people_business_profiles' table...");
  const { data: profiles, error: profilesError } = await supabase
    .from("people_business_profiles")
    .select("*")
    .limit(1);

  if (profilesError) {
    console.error("   ❌ Error:", profilesError.message);
  } else {
    console.log("   ✅ Business profiles table accessible");
    console.log("   📊 Sample count:", profiles?.length || 0);
  }

  console.log("\n✅ Database connection test complete!");
}

testConnection().catch((error) => {
  console.error("\n❌ Test failed:", error);
  process.exit(1);
});
