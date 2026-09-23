#include "ManusGlove.hpp"

#include <chrono>
#include <algorithm>
#include <cctype>
#include <cstring>
#include <cmath>
#include <iostream>
#include <memory>
#include <thread>

namespace manus_glove
{

ManusGlove* ManusGlove::s_Instance = nullptr;

namespace
{
std::string ToLower(std::string p_Value)
{
    std::transform(p_Value.begin(), p_Value.end(), p_Value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return p_Value;
}

bool ContainsAnyDiagnosticKeyword(const std::string& p_Value)
{
    const std::string t_Lower = ToLower(p_Value);
    return t_Lower.find("dongle") != std::string::npos
           || t_Lower.find("stall") != std::string::npos
           || t_Lower.find("license") != std::string::npos
           || t_Lower.find("version") != std::string::npos
           || t_Lower.find("sanity") != std::string::npos
           || t_Lower.find("glove") != std::string::npos
           || t_Lower.find("disconnect") != std::string::npos
           || t_Lower.find("error") != std::string::npos
           || t_Lower.find("warn") != std::string::npos;
}

const char* LogSeverityName(LogSeverity p_Severity)
{
    switch (p_Severity)
    {
    case LogSeverity::LogSeverity_Debug:
        return "debug";
    case LogSeverity::LogSeverity_Info:
        return "info";
    case LogSeverity::LogSeverity_Warn:
        return "warn";
    case LogSeverity::LogSeverity_Error:
        return "error";
    default:
        return "unknown";
    }
}

const char* SystemMessageTypeName(SystemMessageType p_Type)
{
    switch (p_Type)
    {
    case SystemMessageType::SystemMessageType_LibDebugReplugDongle:
        return "LibDebugReplugDongle";
    case SystemMessageType::SystemMessageType_LibDebugRxStall:
        return "LibDebugRxStall";
    case SystemMessageType::SystemMessageType_LibDebugTxStall:
        return "LibDebugTxStall";
    case SystemMessageType::SystemMessageType_SessionRefusedDueToLicenseIssue:
        return "SessionRefusedDueToLicenseIssue";
    case SystemMessageType::SystemMessageType_SessionConnectionVersionMismatch:
        return "SessionConnectionVersionMismatch";
    case SystemMessageType::SystemMessageType_DeprecatedLicense:
        return "DeprecatedLicense";
    case SystemMessageType::SystemMessageType_GloveSanityErrorPSOCInit:
        return "GloveSanityErrorPSOCInit";
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCBatV:
        return "GloveSanityErrorQCBatV";
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCLRACalib:
        return "GloveSanityErrorQCLRACalib";
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCFlexInit:
        return "GloveSanityErrorQCFlexInit";
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCIMUInit:
        return "GloveSanityErrorQCIMUInit";
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCIMUCalib:
        return "GloveSanityErrorQCIMUCalib";
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCID:
        return "GloveSanityErrorQCID";
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCInterCPU:
        return "GloveSanityErrorQCInterCPU";
    default:
        return "Other";
    }
}

bool IsDiagnosticSystemMessage(SystemMessageType p_Type)
{
    switch (p_Type)
    {
    case SystemMessageType::SystemMessageType_LibDebugReplugDongle:
    case SystemMessageType::SystemMessageType_LibDebugRxStall:
    case SystemMessageType::SystemMessageType_LibDebugTxStall:
    case SystemMessageType::SystemMessageType_SessionRefusedDueToLicenseIssue:
    case SystemMessageType::SystemMessageType_SessionConnectionVersionMismatch:
    case SystemMessageType::SystemMessageType_DeprecatedLicense:
    case SystemMessageType::SystemMessageType_GloveSanityErrorPSOCInit:
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCBatV:
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCLRACalib:
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCFlexInit:
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCIMUInit:
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCIMUCalib:
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCID:
    case SystemMessageType::SystemMessageType_GloveSanityErrorQCInterCPU:
        return true;
    default:
        return false;
    }
}

int SideFromString(const std::string& p_Side)
{
    if (p_Side == "left" || p_Side == "Left" || p_Side == "L")
        return Side::Side_Left;
    if (p_Side == "right" || p_Side == "Right" || p_Side == "R")
        return Side::Side_Right;
    return Side::Side_Invalid;
}

GloveStartupStatus StartupStatusFromGlove(const GloveLandscapeData& p_Glove)
{
    GloveStartupStatus t_Status;
    t_Status.id = p_Glove.id;
    t_Status.dongleId = p_Glove.dongleID;
    t_Status.batteryPercentage = p_Glove.batteryPercentage;
    t_Status.transmissionStrength = p_Glove.transmissionStrength;
    t_Status.pairedState = static_cast<int>(p_Glove.pairedState);
    t_Status.excluded = p_Glove.excluded;
    t_Status.valid = true;
    return t_Status;
}

void PrintGloveStartupStatus(const char* p_Label, const GloveStartupStatus& p_Status)
{
    std::cout << "[manus_glove] " << p_Label << ": ";
    if (!p_Status.valid)
    {
        std::cout << "not detected" << std::endl;
        return;
    }

    std::cout << "id=" << p_Status.id
              << " dongle=" << p_Status.dongleId
              << " battery=" << p_Status.batteryPercentage << "%"
              << " tx=" << p_Status.transmissionStrength
              << " paired_state=" << p_Status.pairedState
              << " excluded=" << (p_Status.excluded ? "true" : "false")
              << std::endl;
}
} // namespace

ManusGlove::ManusGlove()
{
    m_StartTime = std::chrono::steady_clock::now();
    s_Instance = this;
}

ManusGlove::~ManusGlove()
{
    Disconnect();
    if (s_Instance == this)
        s_Instance = nullptr;
}

bool ManusGlove::Connect(const std::string& p_Mode, bool p_WorldCoordinates, int p_TimeoutSeconds)
{
    if (m_Connected)
        return true;

    if (!InitializeSdk(p_Mode, p_WorldCoordinates))
    {
        CoreSdk_ShutDown();
        return false;
    }

    const bool t_Loopback = (p_Mode == "local");
    if (!ConnectToFirstHost(t_Loopback, p_TimeoutSeconds))
    {
        CoreSdk_ShutDown();
        return false;
    }

    // Optional: let the SDK pick hand motion source automatically.
    CoreSdk_SetRawSkeletonHandMotion(HandMotion::HandMotion_Auto);

    m_WorldCoordinates = p_WorldCoordinates;
    m_Connected = true;
    WaitForStartupDiagnostics(3);
    PrintStartupDiagnostics();
    return true;
}

bool ManusGlove::InitializeSdk(const std::string& p_Mode, bool p_WorldCoordinates)
{
    m_Integrated = (p_Mode == "integrated");

    SDKReturnCode t_Init = m_Integrated ? CoreSdk_InitializeIntegrated()
                                        : CoreSdk_InitializeCore();
    if (t_Init != SDKReturnCode::SDKReturnCode_Success)
        return false;

    if (CoreSdk_RegisterCallbackForOnLog(*OnLogCallback) != SDKReturnCode::SDKReturnCode_Success)
        return false;
    if (CoreSdk_RegisterCallbackForSystemStream(*OnSystemStreamCallback) != SDKReturnCode::SDKReturnCode_Success)
        return false;
    if (CoreSdk_RegisterCallbackForRawSkeletonStream(*OnRawSkeletonStreamCallback) != SDKReturnCode::SDKReturnCode_Success)
        return false;
    if (CoreSdk_RegisterCallbackForLandscapeStream(*OnLandscapeStreamCallback) != SDKReturnCode::SDKReturnCode_Success)
        return false;
    if (CoreSdk_RegisterCallbackForErgonomicsStream(*OnErgonomicsStreamCallback) != SDKReturnCode::SDKReturnCode_Success)
        return false;

    // Coordinate system: z-up, x-from-viewer, right-handed, meters.
    // p_WorldCoordinates is the plan-A global/local switch and is fixed for the
    // lifetime of this connection.
    CoordinateSystemVUH t_VUH;
    CoordinateSystemVUH_Init(&t_VUH);
    t_VUH.handedness = Side::Side_Right;
    t_VUH.up = AxisPolarity::AxisPolarity_PositiveZ;
    t_VUH.view = AxisView::AxisView_XFromViewer;
    t_VUH.unitScale = 1.0f; // meters

    if (CoreSdk_InitializeCoordinateSystemWithVUH(t_VUH, p_WorldCoordinates) != SDKReturnCode::SDKReturnCode_Success)
        return false;

    return true;
}

bool ManusGlove::ConnectToFirstHost(bool p_LoopbackOnly, int p_TimeoutSeconds)
{
    const auto t_Deadline = std::chrono::steady_clock::now() + std::chrono::seconds(p_TimeoutSeconds);

    do
    {
        if (CoreSdk_LookForHosts(1, p_LoopbackOnly) == SDKReturnCode::SDKReturnCode_Success)
        {
            uint32_t t_NumHosts = 0;
            if (CoreSdk_GetNumberOfAvailableHostsFound(&t_NumHosts) == SDKReturnCode::SDKReturnCode_Success
                && t_NumHosts > 0)
            {
                std::unique_ptr<ManusHost[]> t_Hosts(new ManusHost[t_NumHosts]);
                if (CoreSdk_GetAvailableHostsFound(t_Hosts.get(), t_NumHosts) == SDKReturnCode::SDKReturnCode_Success)
                {
                    SDKReturnCode t_Conn = CoreSdk_ConnectToHost(t_Hosts[0]);
                    if (t_Conn == SDKReturnCode::SDKReturnCode_Success)
                        return true;
                }
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    } while (std::chrono::steady_clock::now() < t_Deadline);

    return false;
}

uint64_t ManusGlove::ElapsedMs() const
{
    return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
                                     std::chrono::steady_clock::now() - m_StartTime)
                                     .count());
}

void ManusGlove::PushDebugEvent(DebugEvent p_Event)
{
    std::lock_guard<std::mutex> t_Lock(m_DebugMutex);
    p_Event.sequence = ++m_DebugSequence;
    p_Event.timestampMs = ElapsedMs();
    m_DebugEvents.push_back(std::move(p_Event));
    while (m_DebugEvents.size() > kMaxDebugEvents)
        m_DebugEvents.pop_front();
}

std::vector<DebugEvent> ManusGlove::GetDebugEvents(bool p_Clear)
{
    std::lock_guard<std::mutex> t_Lock(m_DebugMutex);
    std::vector<DebugEvent> t_Out(m_DebugEvents.begin(), m_DebugEvents.end());
    if (p_Clear)
        m_DebugEvents.clear();
    return t_Out;
}

void ManusGlove::WaitForStartupDiagnostics(int p_TimeoutSeconds)
{
    const auto t_Deadline = std::chrono::steady_clock::now() + std::chrono::seconds(p_TimeoutSeconds);

    while (std::chrono::steady_clock::now() < t_Deadline)
    {
        bool t_HasLandscape = false;
        bool t_HasAnyGlove = false;
        bool t_HasSkeleton = false;
        bool t_HasErgo = false;

        {
            std::lock_guard<std::mutex> t_Lock(m_LandscapeMutex);
            t_HasLandscape = m_LandscapeReceived;
            t_HasAnyGlove = (m_LeftGloveId != 0 || m_RightGloveId != 0 || m_LandscapeGloveCount > 0);
        }
        {
            std::lock_guard<std::mutex> t_Lock(m_SkeletonMutex);
            t_HasSkeleton = (m_RawSkeletonFrameCount > 0);
        }
        {
            std::lock_guard<std::mutex> t_Lock(m_ErgoMutex);
            t_HasErgo = (m_ErgonomicsFrameCount > 0);
        }

        if (t_HasLandscape && t_HasAnyGlove && t_HasSkeleton && t_HasErgo)
            return;

        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
}

void ManusGlove::PrintStartupDiagnostics()
{
    uint32_t t_LeftId = 0;
    uint32_t t_RightId = 0;
    uint32_t t_GloveCount = 0;
    uint32_t t_DongleCount = 0;
    bool t_LandscapeReceived = false;
    GloveStartupStatus t_LeftStatus;
    GloveStartupStatus t_RightStatus;
    bool t_LeftSkeletonValid = false;
    bool t_RightSkeletonValid = false;
    uint64_t t_SkeletonFrames = 0;
    bool t_LeftErgoValid = false;
    bool t_RightErgoValid = false;
    uint64_t t_ErgoFrames = 0;

    {
        std::lock_guard<std::mutex> t_Lock(m_LandscapeMutex);
        t_LeftId = m_LeftGloveId;
        t_RightId = m_RightGloveId;
        t_GloveCount = m_LandscapeGloveCount;
        t_DongleCount = m_LandscapeDongleCount;
        t_LandscapeReceived = m_LandscapeReceived;
        t_LeftStatus = m_LeftStartupStatus;
        t_RightStatus = m_RightStartupStatus;
    }
    {
        std::lock_guard<std::mutex> t_Lock(m_SkeletonMutex);
        t_LeftSkeletonValid = m_LeftSkeleton.valid;
        t_RightSkeletonValid = m_RightSkeleton.valid;
        t_SkeletonFrames = m_RawSkeletonFrameCount;
    }
    {
        std::lock_guard<std::mutex> t_Lock(m_ErgoMutex);
        t_LeftErgoValid = m_LeftErgoValid;
        t_RightErgoValid = m_RightErgoValid;
        t_ErgoFrames = m_ErgonomicsFrameCount;
    }

    std::cout << "[manus_glove] SDK connected"
              << " mode=" << (m_Integrated ? "integrated" : "core")
              << " coordinates=" << (m_WorldCoordinates ? "world" : "local")
              << std::endl;
    std::cout << "[manus_glove] landscape="
              << (t_LandscapeReceived ? "received" : "not received")
              << " gloves=" << t_GloveCount
              << " dongles=" << t_DongleCount
              << " left_id=" << t_LeftId
              << " right_id=" << t_RightId
              << std::endl;
    PrintGloveStartupStatus("left", t_LeftStatus);
    PrintGloveStartupStatus("right", t_RightStatus);
    std::cout << "[manus_glove] first frames: skeleton="
              << (t_SkeletonFrames > 0 ? "yes" : "no")
              << " (left=" << (t_LeftSkeletonValid ? "yes" : "no")
              << ", right=" << (t_RightSkeletonValid ? "yes" : "no")
              << "), ergonomics=" << (t_ErgoFrames > 0 ? "yes" : "no")
              << " (left=" << (t_LeftErgoValid ? "yes" : "no")
              << ", right=" << (t_RightErgoValid ? "yes" : "no")
              << ")"
              << std::endl;
    std::cout.flush();
}

void ManusGlove::Disconnect()
{
    if (!m_Connected)
        return;
    CoreSdk_ShutDown();
    m_Connected = false;

    {
        std::lock_guard<std::mutex> t_LandscapeLock(m_LandscapeMutex);
        m_LeftGloveId = 0;
        m_RightGloveId = 0;
        m_LandscapeGloveCount = 0;
        m_LandscapeDongleCount = 0;
        m_LandscapeReceived = false;
        m_LeftStartupStatus = GloveStartupStatus{};
        m_RightStartupStatus = GloveStartupStatus{};
    }
    {
        std::lock_guard<std::mutex> t_SkelLock(m_SkeletonMutex);
        m_LeftSkeleton = SkeletonSnapshot{};
        m_RightSkeleton = SkeletonSnapshot{};
        m_RawSkeletonFrameCount = 0;
    }
    {
        std::lock_guard<std::mutex> t_ErgoLock(m_ErgoMutex);
        m_LeftErgo = {};
        m_RightErgo = {};
        m_LeftErgoValid = false;
        m_RightErgoValid = false;
        m_ErgonomicsFrameCount = 0;
    }
}

uint32_t ManusGlove::GloveIdForSide(int p_Side)
{
    std::lock_guard<std::mutex> t_Lock(m_LandscapeMutex);
    if (p_Side == Side::Side_Left)
        return m_LeftGloveId;
    if (p_Side == Side::Side_Right)
        return m_RightGloveId;
    return 0;
}

uint32_t ManusGlove::GetGloveId(const std::string& p_Side)
{
    return GloveIdForSide(SideFromString(p_Side));
}

int ManusGlove::VibrateFingers(const std::string& p_Side, const std::array<float, 5>& p_Powers)
{
    const uint32_t t_GloveId = GetGloveId(p_Side);
    if (!m_Connected || t_GloveId == 0)
        return -1;
    for (float t_Power : p_Powers)
    {
        if (!std::isfinite(t_Power) || t_Power < 0.0f || t_Power > 1.0f)
            return -3;
    }
    const SDKReturnCode t_Result = CoreSdk_VibrateFingersForGlove(t_GloveId, p_Powers.data());
    return t_Result == SDKReturnCode::SDKReturnCode_Success ? 1 : -2;
}

// ------------------------------------------------------------------------------------------------
// Callbacks (SDK threads). They only touch C++ members under mutexes — no Python interaction.
// ------------------------------------------------------------------------------------------------

void ManusGlove::OnLogCallback(LogSeverity p_Severity, const char* const p_Log, uint32_t p_Length)
{
    if (!s_Instance || p_Log == nullptr)
        return;

    std::string t_Message(p_Log, p_Log + p_Length);
    const bool t_IsImportant = p_Severity == LogSeverity::LogSeverity_Warn
                               || p_Severity == LogSeverity::LogSeverity_Error
                               || ContainsAnyDiagnosticKeyword(t_Message);
    if (!t_IsImportant)
        return;

    DebugEvent t_Event;
    t_Event.source = "sdk_log";
    t_Event.severity = static_cast<int>(p_Severity);
    t_Event.severityName = LogSeverityName(p_Severity);
    t_Event.message = std::move(t_Message);
    s_Instance->PushDebugEvent(std::move(t_Event));
}

void ManusGlove::OnSystemStreamCallback(const SystemMessage* const p_SystemMessage)
{
    if (!s_Instance || p_SystemMessage == nullptr)
        return;

    if (!IsDiagnosticSystemMessage(p_SystemMessage->type))
        return;

    DebugEvent t_Event;
    t_Event.source = "system";
    t_Event.type = static_cast<int>(p_SystemMessage->type);
    t_Event.typeName = SystemMessageTypeName(p_SystemMessage->type);
    t_Event.message = p_SystemMessage->infoString;
    t_Event.infoUInt = p_SystemMessage->infoUInt;
    s_Instance->PushDebugEvent(std::move(t_Event));
}

void ManusGlove::OnLandscapeStreamCallback(const Landscape* const p_Landscape)
{
    if (!s_Instance || p_Landscape == nullptr)
        return;

    uint32_t t_Left = 0;
    uint32_t t_Right = 0;
    GloveStartupStatus t_LeftStatus;
    GloveStartupStatus t_RightStatus;
    for (uint32_t i = 0; i < p_Landscape->gloveDevices.gloveCount; i++)
    {
        const GloveLandscapeData& t_Glove = p_Landscape->gloveDevices.gloves[i];
        if (t_Left == 0 && t_Glove.side == Side::Side_Left)
        {
            t_Left = t_Glove.id;
            t_LeftStatus = StartupStatusFromGlove(t_Glove);
        }
        else if (t_Right == 0 && t_Glove.side == Side::Side_Right)
        {
            t_Right = t_Glove.id;
            t_RightStatus = StartupStatusFromGlove(t_Glove);
        }
    }

    std::lock_guard<std::mutex> t_Lock(s_Instance->m_LandscapeMutex);
    s_Instance->m_LeftGloveId = t_Left;
    s_Instance->m_RightGloveId = t_Right;
    s_Instance->m_LandscapeGloveCount = p_Landscape->gloveDevices.gloveCount;
    s_Instance->m_LandscapeDongleCount = p_Landscape->gloveDevices.dongleCount;
    s_Instance->m_LandscapeReceived = true;
    s_Instance->m_LeftStartupStatus = t_LeftStatus;
    s_Instance->m_RightStartupStatus = t_RightStatus;
}

void ManusGlove::OnRawSkeletonStreamCallback(const SkeletonStreamInfo* const p_Info)
{
    if (!s_Instance || p_Info == nullptr)
        return;

    // Resolve side ids once for this callback.
    uint32_t t_LeftId, t_RightId;
    {
        std::lock_guard<std::mutex> t_Lock(s_Instance->m_LandscapeMutex);
        t_LeftId = s_Instance->m_LeftGloveId;
        t_RightId = s_Instance->m_RightGloveId;
    }

    for (uint32_t s = 0; s < p_Info->skeletonsCount; s++)
    {
        RawSkeletonInfo t_SkelInfo;
        if (CoreSdk_GetRawSkeletonInfo(s, &t_SkelInfo) != SDKReturnCode::SDKReturnCode_Success)
            continue;

        std::vector<SkeletonNode> t_Nodes(t_SkelInfo.nodesCount);
        if (t_SkelInfo.nodesCount > 0
            && CoreSdk_GetRawSkeletonData(s, t_Nodes.data(), t_SkelInfo.nodesCount) != SDKReturnCode::SDKReturnCode_Success)
            continue;

        SkeletonSnapshot t_Snap;
        t_Snap.rows = static_cast<int>(t_SkelInfo.nodesCount);
        t_Snap.cols = 10;
        t_Snap.gloveId = t_SkelInfo.gloveId;
        t_Snap.valid = true;
        t_Snap.data.reserve(static_cast<size_t>(t_Snap.rows) * 10);
        for (const SkeletonNode& n : t_Nodes)
        {
            t_Snap.data.push_back(n.transform.position.x);
            t_Snap.data.push_back(n.transform.position.y);
            t_Snap.data.push_back(n.transform.position.z);
            t_Snap.data.push_back(n.transform.rotation.w);
            t_Snap.data.push_back(n.transform.rotation.x);
            t_Snap.data.push_back(n.transform.rotation.y);
            t_Snap.data.push_back(n.transform.rotation.z);
            t_Snap.data.push_back(n.transform.scale.x);
            t_Snap.data.push_back(n.transform.scale.y);
            t_Snap.data.push_back(n.transform.scale.z);
        }

        std::lock_guard<std::mutex> t_Lock(s_Instance->m_SkeletonMutex);
        s_Instance->m_RawSkeletonFrameCount++;
        if (t_RightId != 0 && t_SkelInfo.gloveId == t_RightId)
            s_Instance->m_RightSkeleton = std::move(t_Snap);
        else if (t_LeftId != 0 && t_SkelInfo.gloveId == t_LeftId)
            s_Instance->m_LeftSkeleton = std::move(t_Snap);
        else if (t_LeftId == 0 && t_RightId == 0)
            // Landscape not resolved yet: stash into left as a fallback so data isn't lost.
            s_Instance->m_LeftSkeleton = std::move(t_Snap);
    }
}

void ManusGlove::OnErgonomicsStreamCallback(const ErgonomicsStream* const p_Ergo)
{
    if (!s_Instance || p_Ergo == nullptr)
        return;

    uint32_t t_LeftId, t_RightId;
    {
        std::lock_guard<std::mutex> t_Lock(s_Instance->m_LandscapeMutex);
        t_LeftId = s_Instance->m_LeftGloveId;
        t_RightId = s_Instance->m_RightGloveId;
    }

    std::lock_guard<std::mutex> t_Lock(s_Instance->m_ErgoMutex);
    s_Instance->m_ErgonomicsFrameCount++;
    for (uint32_t i = 0; i < p_Ergo->dataCount; i++)
    {
        const ErgonomicsData& t_Data = p_Ergo->data[i];
        if (t_Data.isUserID)
            continue;

        if (t_RightId != 0 && t_Data.id == t_RightId)
        {
            std::memcpy(s_Instance->m_RightErgo.data(), t_Data.data, sizeof(t_Data.data));
            s_Instance->m_RightErgoValid = true;
        }
        else if (t_LeftId != 0 && t_Data.id == t_LeftId)
        {
            std::memcpy(s_Instance->m_LeftErgo.data(), t_Data.data, sizeof(t_Data.data));
            s_Instance->m_LeftErgoValid = true;
        }
    }
}

// ------------------------------------------------------------------------------------------------
// Pull-side getters (called from Python).
// ------------------------------------------------------------------------------------------------

SkeletonSnapshot ManusGlove::GetRawSkeleton(const std::string& p_Side)
{
    const int t_Side = SideFromString(p_Side);
    std::lock_guard<std::mutex> t_Lock(m_SkeletonMutex);
    if (t_Side == Side::Side_Right)
        return m_RightSkeleton;
    return m_LeftSkeleton;
}

std::array<float, ErgonomicsDataType_MAX_SIZE> ManusGlove::GetErgonomics()
{
    std::array<float, ErgonomicsDataType_MAX_SIZE> t_Out{};
    std::lock_guard<std::mutex> t_Lock(m_ErgoMutex);
    // Left half [0..19] from the left glove, right half [20..39] from the right glove.
    const int t_Half = ErgonomicsDataType_MAX_SIZE / 2;
    if (m_LeftErgoValid)
        std::copy(m_LeftErgo.begin(), m_LeftErgo.begin() + t_Half, t_Out.begin());
    if (m_RightErgoValid)
        std::copy(m_RightErgo.begin() + t_Half, m_RightErgo.end(), t_Out.begin() + t_Half);
    return t_Out;
}

std::vector<NodeInfoOut> ManusGlove::GetNodeInfo(const std::string& p_Side)
{
    std::vector<NodeInfoOut> t_Out;
    const uint32_t t_GloveId = GloveIdForSide(SideFromString(p_Side));
    if (t_GloveId == 0)
        return t_Out;

    uint32_t t_NodeCount = 0;
    if (CoreSdk_GetRawSkeletonNodeCount(t_GloveId, t_NodeCount) != SDKReturnCode::SDKReturnCode_Success
        || t_NodeCount == 0)
        return t_Out;

    std::vector<NodeInfo> t_Info(t_NodeCount);
    if (CoreSdk_GetRawSkeletonNodeInfoArray(t_GloveId, t_Info.data(), t_NodeCount) != SDKReturnCode::SDKReturnCode_Success)
        return t_Out;

    t_Out.reserve(t_NodeCount);
    for (const NodeInfo& n : t_Info)
    {
        NodeInfoOut o;
        o.nodeId = n.nodeId;
        o.parentId = n.parentId;
        o.chainType = static_cast<int>(n.chainType);
        o.side = static_cast<int>(n.side);
        o.fingerJointType = static_cast<int>(n.fingerJointType);
        t_Out.push_back(o);
    }
    return t_Out;
}

int ManusGlove::SetCalibration(const std::string& p_Side, const std::vector<uint8_t>& p_Bytes)
{
    if (!m_Connected)
        return -1;

    const uint32_t t_GloveId = GloveIdForSide(SideFromString(p_Side));
    if (t_GloveId == 0 || p_Bytes.empty())
        return -1;

    SetGloveCalibrationReturnCode t_Result = SetGloveCalibrationReturnCode_Error;
    SDKReturnCode t_Sdk = CoreSdk_SetGloveCalibration(
        t_GloveId,
        const_cast<unsigned char*>(p_Bytes.data()),
        static_cast<uint32_t>(p_Bytes.size()),
        &t_Result);

    if (t_Sdk != SDKReturnCode::SDKReturnCode_Success)
        return -2;
    return static_cast<int>(t_Result);
}

} // namespace manus_glove
