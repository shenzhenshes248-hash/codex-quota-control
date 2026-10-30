package cn.codex.quota

import java.util.TimeZone
import org.junit.Assert.*
import org.junit.Test

class ModelsTest {
    @Test fun sortsAndRejectsDuplicateTimes() {
        assertEquals(listOf("07:30", "12:15", "18:45"), sortedTimes(listOf("18:45", "07:30", "12:15")))
        assertThrows(IllegalArgumentException::class.java) { sortedTimes(listOf("07:00", "07:00")) }
        assertThrows(IllegalArgumentException::class.java) { sortedTimes(listOf("24:00")) }
    }
    @Test fun alwaysDisplaysBeijingRegardlessOfPhoneZone() {
        val original = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("America/Los_Angeles"))
            assertEquals("10-31 07:30:00 北京时间", beijingTime("2026-10-30T23:30:00Z"))
            assertEquals("10-31 07:30:00 北京时间", beijingTime("2026-10-31T07:30:00+08:00"))
        } finally { TimeZone.setDefault(original) }
    }
    @Test fun onlyAcceptsHttpsWithoutEmbeddedCredentialsOrRedirectParameters() {
        val token = "a".repeat(48)
        assertEquals("https://api.example.com:8443", ConnectionConfig("https://api.example.com:8443/", token).normalized().address)
        for (url in listOf("http://example.com", "https://user:secret@example.com", "https://example.com?token=test"))
            assertThrows(IllegalArgumentException::class.java) { ConnectionConfig(url, token).normalized() }
    }
    @Test fun acceptsHttpsPublicIpWithoutADomain() {
        val token = "a".repeat(48)
        for (url in listOf("https://38.207.137.194:8443", "https://[2606:4700:4700::1111]:8443"))
            assertEquals(url, ConnectionConfig("$url/", token).normalized().address)
        assertThrows(IllegalArgumentException::class.java) {
            ConnectionConfig("http://38.207.137.194:8443", token).normalized()
        }
    }
}
