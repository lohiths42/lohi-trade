import XCTest
import Combine
@testable import LoHiTrade

@MainActor
final class NetworkMonitorTests: XCTestCase {

    // MARK: - Initial State

    func testInitialStateIsConnected() {
        let sut = NetworkMonitor()
        XCTAssertTrue(sut.isConnected)
        XCTAssertEqual(sut.connectionType, .unknown)
    }

    // MARK: - Connectivity Restored Subject

    func testConnectivityRestoredSubjectExists() {
        let sut = NetworkMonitor()
        // Verify the subject can be subscribed to without error
        var cancellable: AnyCancellable?
        let expectation = XCTestExpectation(description: "subscribed")
        expectation.isInverted = true

        cancellable = sut.connectivityRestored.sink {
            expectation.fulfill()
        }

        // Should not fire without network change
        wait(for: [expectation], timeout: 0.5)
        cancellable?.cancel()
    }

    // MARK: - Start/Stop

    func testStartAndStopDoNotCrash() {
        let sut = NetworkMonitor()
        sut.start()
        // Give it a moment to initialize
        let expectation = XCTestExpectation(description: "started")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            expectation.fulfill()
        }
        wait(for: [expectation], timeout: 1.0)
        sut.stop()
    }

    // MARK: - Connection Type Enum

    func testConnectionTypeRawValues() {
        XCTAssertEqual(NetworkMonitor.ConnectionType.wifi.rawValue, "wifi")
        XCTAssertEqual(NetworkMonitor.ConnectionType.cellular.rawValue, "cellular")
        XCTAssertEqual(NetworkMonitor.ConnectionType.wiredEthernet.rawValue, "wiredEthernet")
        XCTAssertEqual(NetworkMonitor.ConnectionType.unknown.rawValue, "unknown")
    }
}
