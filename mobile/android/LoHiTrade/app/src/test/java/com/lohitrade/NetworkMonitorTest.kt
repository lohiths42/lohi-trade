package com.lohitrade

import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import com.lohitrade.data.cache.NetworkMonitor
import io.mockk.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Unit tests for NetworkMonitor (Req 14.2, 14.3).
 *
 * Verifies connectivity state tracking, connection type mapping,
 * and sync-on-reconnect behavior.
 */
class NetworkMonitorTest {

    private lateinit var connectivityManager: ConnectivityManager
    private lateinit var sut: NetworkMonitor
    private var registeredCallback: ConnectivityManager.NetworkCallback? = null

    @Before
    fun setUp() {
        connectivityManager = mockk(relaxed = true)

        // Capture the registered callback so we can simulate network events
        every {
            connectivityManager.registerNetworkCallback(any<NetworkRequest>(), any<ConnectivityManager.NetworkCallback>())
        } answers {
            registeredCallback = secondArg()
        }

        // Default: no active network
        every { connectivityManager.activeNetwork } returns null
        every { connectivityManager.getNetworkCapabilities(any()) } returns null
    }

    @Test
    fun `initial state is disconnected when no active network`() {
        sut = NetworkMonitor(connectivityManager)
        sut.start()

        assertFalse(sut.isConnected.value)
        assertEquals(NetworkMonitor.ConnectionType.UNKNOWN, sut.connectionType.value)
    }

    @Test
    fun `initial state is connected when active network has internet`() {
        val network = mockk<Network>()
        val caps = mockk<NetworkCapabilities>()
        every { connectivityManager.activeNetwork } returns network
        every { connectivityManager.getNetworkCapabilities(network) } returns caps
        every { caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) } returns true
        every { caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) } returns true
        every { caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) } returns false
        every { caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) } returns false

        sut = NetworkMonitor(connectivityManager)
        sut.start()

        assertTrue(sut.isConnected.value)
        assertEquals(NetworkMonitor.ConnectionType.WIFI, sut.connectionType.value)
    }

    @Test
    fun `onAvailable sets connected to true`() {
        sut = NetworkMonitor(connectivityManager)
        sut.start()

        val network = mockk<Network>()
        registeredCallback?.onAvailable(network)

        assertTrue(sut.isConnected.value)
    }

    @Test
    fun `onLost sets connected to false`() {
        sut = NetworkMonitor(connectivityManager)
        sut.start()

        val network = mockk<Network>()
        registeredCallback?.onAvailable(network)
        assertTrue(sut.isConnected.value)

        registeredCallback?.onLost(network)
        assertFalse(sut.isConnected.value)
    }

    @Test
    fun `onCapabilitiesChanged updates connection type to cellular`() {
        sut = NetworkMonitor(connectivityManager)
        sut.start()

        val network = mockk<Network>()
        val caps = mockk<NetworkCapabilities>()
        every { caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) } returns true
        every { caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) } returns false
        every { caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) } returns true
        every { caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) } returns false

        registeredCallback?.onCapabilitiesChanged(network, caps)

        assertEquals(NetworkMonitor.ConnectionType.CELLULAR, sut.connectionType.value)
        assertTrue(sut.isConnected.value)
    }

    @Test
    fun `connectivity restored emits after disconnect then reconnect`() = runTest {
        val testScope = CoroutineScope(UnconfinedTestDispatcher(testScheduler) + SupervisorJob())
        sut = NetworkMonitor(connectivityManager, testScope)
        sut.start()

        val network = mockk<Network>()

        // Simulate disconnect
        registeredCallback?.onLost(network)
        assertFalse(sut.isConnected.value)

        // Collect connectivity restored events
        var restored = false
        val collectJob = launch(UnconfinedTestDispatcher(testScheduler)) {
            sut.connectivityRestored.first()
            restored = true
        }

        // Simulate reconnect
        registeredCallback?.onAvailable(network)

        // Advance past the 500ms stabilization delay
        advanceTimeBy(600)

        assertTrue(restored)
        collectJob.cancel()
        testScope.cancel()
    }

    @Test
    fun `stop unregisters callback`() {
        sut = NetworkMonitor(connectivityManager)
        sut.start()
        sut.stop()

        verify { connectivityManager.unregisterNetworkCallback(any<ConnectivityManager.NetworkCallback>()) }
    }

    @Test
    fun `connection type maps ethernet correctly`() {
        sut = NetworkMonitor(connectivityManager)
        sut.start()

        val network = mockk<Network>()
        val caps = mockk<NetworkCapabilities>()
        every { caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) } returns true
        every { caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) } returns false
        every { caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) } returns false
        every { caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) } returns true

        registeredCallback?.onCapabilitiesChanged(network, caps)

        assertEquals(NetworkMonitor.ConnectionType.ETHERNET, sut.connectionType.value)
    }
}
